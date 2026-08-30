# -*- coding: utf-8 -*-
"""
唯一计算入口 (供 web JobManager 以子进程调用, 也可独立命令行使用):

    python -m orbcalc.run_cli --config runs/<job>/config.json --jobs 8 --outdir runs/<job>

行为与 temp/EVVEJU_TOF_1DSM_mp.py 主流程逐位一致 (cfg 驱动):
    [1] 扫描 -> [2] 细化 (run_scan)   | [3] 弹道播种 (run_seed, smoke 自动跳过)
    [w] 内置热启动 (warm_x 非空)      | [4] 宽 J->U 压缩 (run_compress)
    [5] 紧 J->U 前沿压缩 (run_frontier)| [6] pick_best -> 报告/汇总/绘图数据

产物 (outdir 内):
    log.txt        全程日志 (含阶段 print, stdout 同步)
    best_x.npy     最优设计向量
    result.json    结构化摘要 (网页结果卡)
    plot.json      3D 图数据 (Plotly)
    trajectory.png 静态图 (Agg, 尽力而为)
退出码: 0 = 完成 (含\"无可行解\"); 2 = 流水线失败/异常。
"""
from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import sys
import time
import traceback


def _force_utf8_stdio():
    """无论控制台/重定向目标是什么代码页, 统一 stdout/stderr 为 UTF-8\n    (报告文本含 ²/Δv 等字符, GBK 控制台会 UnicodeEncodeError)."""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

import numpy as np

from .config import TrajConfig
from .udp import TOF_UDP, DSM_UDP
from .decode_report import decode, report, summarize
from .plot_data import build_plot_json, render_png
from .stages import (phase_scan_mp, phase_refine_mp, phase_ballistic_seed_mp,
                     compress_pass_mp, pick_best)


def log(msg, logf):
    print(msg, flush=True)
    logf.write(msg + "\n")
    logf.flush()


def run(args):
    cfg = TrajConfig.from_json(path=args.config)
    if args.jobs and args.jobs > 0:
        cfg.jobs = int(args.jobs)
    cfg.validate()

    outdir = os.path.abspath(args.outdir)
    os.makedirs(outdir, exist_ok=True)
    log_path = os.path.join(outdir, "log.txt")
    logf = open(log_path, "a", encoding="utf-8")

    t_start = time.time()
    summary = {"job": cfg.name, "status": "ok", "error": None}
    try:
        import pykep as pk
        import pygmo as pg
        log(f"pykep {pk.__version__}  pygmo {pg.__version__}  numpy {np.__version__}", logf)
        log(f"seq = {cfg.seq},  DSM limit = {cfg.dsm_limit_ms:.0f} m/s,  "
            f"objective = {cfg.objective},  jobs = {cfg.jobs},  smoke = {cfg.smoke}", logf)

        candidates = []
        from concurrent.futures import ProcessPoolExecutor
        from contextlib import nullcontext

        # 仅当存在并行阶段 (扫描/压缩) 时创建进程池, 纯评估任务零进程开销
        need_pool = cfg.run_scan or cfg.run_compress or cfg.run_frontier
        _ctx = ProcessPoolExecutor(max_workers=cfg.jobs) if need_pool else nullcontext(None)
        with _ctx as ex:
            if cfg.run_scan:
                cands = phase_scan_mp(ex, cfg)
                best_ref = phase_refine_mp(ex, cfg, cands)
                if best_ref is None:
                    log("[main] refine failed", logf)
                    summary["status"] = "error"
                    summary["error"] = "refine failed (all windows sade failed)"
                    return 2
                f_ref, x_ref, info_ref, udp_ref = best_ref
                candidates.append((x_ref, udp_ref))
                if cfg.run_seed and not cfg.smoke:
                    x_seed = phase_ballistic_seed_mp(ex, cfg, x_ref)
                    candidates.append((x_seed, DSM_UDP(cfg, t0=[x_seed[0] - 30, x_seed[0] + 30])))

            if cfg.warm_x is not None:
                try:
                    uw = TOF_UDP(cfg, t0=[cfg.warm_x[0] - 30, cfg.warm_x[0] + 30])
                    iw = decode(cfg.warm_x, uw.udp)
                    log(f"[warn] 内置热启动: TOF={sum(iw['tofs']):.0f} d "
                        f"({sum(iw['tofs']) / 365.25:.2f} yr)  DSM={iw['dsm_total']:.0f} m/s", logf)
                    candidates.append((cfg.warm_x, uw))
                except Exception as e:
                    log(f"[warn] skipped: {e}", logf)

            if (cfg.run_compress or cfg.run_frontier) and candidates:
                def _key(item):
                    info = decode(item[0], item[1].udp)
                    return (0 if info["dsm_total"] <= cfg.dsm_limit_ms else 1,
                            sum(info["tofs"]))
                candidates.sort(key=_key)
                seeds = candidates[:2]
                if cfg.run_compress:
                    for k, (sx, sudp) in enumerate(seeds):
                        xw = compress_pass_mp(ex, cfg, sx, f"4/6 compress wide #{k + 1}",
                                              [2500, 4300], cfg.penalty[0], cfg.penalty[1],
                                              smoke=cfg.smoke)
                        candidates.append((xw, TOF_UDP(cfg, t0=[sx[0] - 30, sx[0] + 30])))
                if cfg.run_frontier:
                    bi, bx, budp = pick_best(cfg, candidates)
                    xf = compress_pass_mp(ex, cfg, bx, "5/6 frontier tight",
                                          [2200, 2900], cfg.frontier_penalty[0],
                                          cfg.frontier_penalty[1], smoke=cfg.smoke)
                    candidates.append((xf, TOF_UDP(cfg, t0=[xf[0] - 30, xf[0] + 30])))

        if not candidates:
            log("[main] no candidates", logf)
            summary["status"] = "no_candidates"
            _write_artifacts(args, cfg, None, None, summary, logf, t_start)
            return 0

        bi, bx, budp = pick_best(cfg, candidates)
        title = f"*** BEST {cfg.name} SOLUTION ***"
        log("\n" + report(bi, cfg, title) + "\n", logf)
        summary["warm_used"] = cfg.warm_x is not None
        _write_artifacts(args, cfg, bi, bx, summary, logf, t_start)
        log(f"[main] done in {time.time() - t_start:.1f} s", logf)
        return 0
    except KeyboardInterrupt:
        summary["status"] = "cancelled"
        _write_result(args, summary, logf)
        log("[main] interrupted", logf)
        return 130
    except Exception:
        summary["status"] = "error"
        summary["error"] = traceback.format_exc()
        log("[main] error:\n" + summary["error"], logf)
        _write_result(args, summary, logf)
        return 2
    finally:
        # 兜底: 异常/退出时释放所有 multiprocessing 子进程 (防孤儿池 worker)。
        # 正常完成时池已由 with 回收, active_children 为空 -> 无操作;
        # 池 broken / 阶段崩溃时残留 worker 在这里被终止。
        try:
            for _ch in multiprocessing.active_children():
                _ch.terminate()
        except Exception:
            pass
        logf.close()


def _write_artifacts(args, cfg, info, bx, summary, logf, t_start):
    if info is not None:
        summary.update(summarize(info, cfg))
        summary["elapsed_s"] = round(time.time() - t_start, 1)
        np.save(os.path.join(args.outdir, "best_x.npy"), np.array(bx))
        with open(os.path.join(args.outdir, "plot.json"), "w", encoding="utf-8") as f:
            json.dump(build_plot_json(cfg, info), f, ensure_ascii=False)
        try:
            render_png(cfg, info, os.path.join(args.outdir, "trajectory.png"))
            log(f"[artifacts] png -> {os.path.join(args.outdir, 'trajectory.png')}", logf)
        except Exception as e:
            log(f"[artifacts] png skipped: {e}", logf)
    summary["elapsed_s"] = round(time.time() - t_start, 1)
    _write_result(args, summary, logf)


def _write_result(args, summary, logf):
    with open(os.path.join(args.outdir, "result.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False)
    log(f"[result] -> {os.path.join(args.outdir, 'result.json')}", logf)


def main():
    _force_utf8_stdio()
    # PyInstaller 冻结: ProcessPoolExecutor spawn 需要 multiprocessing 初始化
    import multiprocessing
    multiprocessing.freeze_support()
    ap = argparse.ArgumentParser(description="orbcalc 计算入口 (web 子进程 / CLI)")
    ap.add_argument("--config", required=True, help="TrajConfig JSON 路径")
    ap.add_argument("--jobs", type=int, default=0, help="覆盖 cfg.jobs (0 = 用配置值)")
    ap.add_argument("--outdir", required=True, help="产物目录 (log/result/plot/best_x)")
    args = ap.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()