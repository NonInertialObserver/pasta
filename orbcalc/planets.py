# -*- coding: utf-8 -*-
"""
行星混合模型: de440s 精密星历 (位置/速度) + JPL LP 物理参数 (μ, 半径)。

- 来源: temp/EVVEJU_TOF_1DSM_mp.py 的 HybridPlanet / make_planet。
- 注册表按 TAG 提供 (spice 名, jpl 名, 默认安全半径)。
- build_seq(cfg): 按 cfg.seq 构建 pk.planet 序列 (进程内缓存, spawn worker 各自重建)。
"""
from __future__ import annotations

import pykep as pk

# ---------------------------------------------------------------------------
# 行星注册表: TAG -> (SPICE 名, JPL LP 名, 默认安全半径 m | None)
# 注: 安全半径 = 飞掠下限。岩质行星 = 半径 + 200 km; 巨行星 = 2 × 赤道半径。
# ---------------------------------------------------------------------------
REGISTRY = {
    "MERCURY": ("MERCURY", "mercury", 2440.0e3 + 200.0e3),
    "VENUS":   ("VENUS", "venus", 6052.0e3 + 200.0e3),            # 地表以上 200 km
    "EARTH":   ("EARTH", "earth", 6578.137e3),                    # ~200 km
    "MARS":    ("MARS BARYCENTER", "mars", 3389.5e3 + 200.0e3),
    "JUPITER": ("JUPITER BARYCENTER", "jupiter", 2.0 * 71492e3),
    "SATURN":  ("SATURN BARYCENTER", "saturn", 2.0 * 58232e3),
    "URANUS":  ("URANUS BARYCENTER", "uranus", None),
    "NEPTUNE": ("NEPTUNE BARYCENTER", "neptune", 2.0 * 24622e3),
}
DEFAULT_SAFE_RADIUS = {tag: v[2] for tag, v in REGISTRY.items()}

# 简名 (报告/绘图用) — 同一 TAG 多次出现时自动加序号 (Venus1, Venus2, ...)
TAG_SHORT = {
    "MERCURY": "Mercury", "VENUS": "Venus", "EARTH": "Earth",
    "MARS": "Mars", "JUPITER": "Jupiter", "SATURN": "Saturn",
    "URANUS": "Uranus", "NEPTUNE": "Neptune",
}


class HybridPlanet:
    def __init__(self, eph, phys, jpl_name, safe_radius_m=None):
        self._eph = eph
        self._phys = phys
        self._jpl = jpl_name
        self._safe = safe_radius_m

    def eph(self, when):
        return self._eph.eph(when)

    def get_name(self):
        return self._phys.get_name() if hasattr(self._phys, "get_name") else self._jpl

    def get_mu_self(self):
        return self._phys.mu_self

    def get_mu_central_body(self):
        return self._phys.mu_central_body

    def get_radius(self):
        return self._phys.radius

    def get_safe_radius(self):
        return self._safe if self._safe is not None else self._phys.safe_radius

    @property
    def mu_self(self):
        return self._phys.mu_self

    @property
    def mu_central_body(self):
        return self._phys.mu_central_body

    @property
    def radius(self):
        return self._phys.radius

    @property
    def safe_radius(self):
        return self._safe if self._safe is not None else self._phys.safe_radius

    def __str__(self):
        return f"{self._jpl} (de440s eph)"


def make_planet(spice, jpl, safe_radius_m=None):
    eph = pk.planet(pk.udpla.de440s(spice, "ECLIPJ2000", "SSB"))
    phys = pk.planet(pk.udpla.jpl_lp(jpl))
    return pk.planet(HybridPlanet(eph, phys, jpl, safe_radius_m))


_cache = {}


def get_planet(tag):
    """按 TAG 构建 pk.planet (进程内缓存)."""
    if tag not in _cache:
        spice, jpl, _def_safe = REGISTRY.get(tag, (None, None, None))
        if spice is None:
            raise KeyError(f"未知行星 TAG: {tag}")
        _cache[tag] = make_planet(spice, jpl)
    return _cache[tag]


def planet_safe_radius(tag, cfg):
    """行星安全半径: cfg.safe_radius 覆盖优先, 否则注册表默认."""
    if tag in cfg.safe_radius:
        return float(cfg.safe_radius[tag])
    _def = REGISTRY.get(tag, (None, None, None))[2]
    return _def  # None → 用物理行星自带 safe_radius


def build_seq(cfg):
    """按 cfg.seq 构建 (SEQ: [pk.planet], NAMES: [str]) — 进程内缓存.

    safe_radius 覆盖在行星构建时即生效 (HybridPlanet._safe)。
    """
    key = (tuple(cfg.seq), tuple(sorted((k, str(v)) for k, v in cfg.safe_radius.items())))
    if key in _cache:
        return _cache[key]
    seq, names = [], []
    counts = {}
    for tag in cfg.seq:
        counts[tag] = counts.get(tag, 0) + 1
        tag_safe = planet_safe_radius(tag, cfg)
        spice, jpl, _ = REGISTRY.get(tag, (None, None, None))
        if spice is None:
            raise KeyError(f"未知行星 TAG: {tag}")
        seq.append(make_planet(spice, jpl, tag_safe))
        short = TAG_SHORT.get(tag, tag)
        names.append(f"{short}{counts[tag]}" if counts[tag] > 1 else short)
    _cache[key] = (seq, names)
    return _cache[key]