# PASTA — Parallel Astrodynamic Solver for Trajectory Analysis

平行天体动力学求解器：配置驱动（浏览器前端配置 → 后端并行搜索）的 MGA-1DSM 弹弓轨道优化工具。

- 前端：本地 Web 界面 (`python main.py` → http://127.0.0.1:8765)
- 后端：Flask + 每任务子进程 + multiprocessing 并行搜索 (扫描 → 细化 → 播种 → 压缩 → 前沿)
- 引擎：pykep (mga_1dsm / lambert) + pygmo

**license: GNU GPL v3**

This project is licensed under the [GPL-3.0 License](https://www.gnu.org/licenses/gpl-3.0.txt)

![GPLv3-logo](https://www.gnu.org/graphics/gplv3-with-text-136x68.png)
