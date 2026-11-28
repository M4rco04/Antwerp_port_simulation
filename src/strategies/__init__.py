"""VTS strategies (docs/VTS_API.md): one module per strategy, each a subclass of vts_api.Strategy with a name.

    baseline          the first-come-first-served VTS the model is calibrated with (the reference)
    container_first   an example: the baseline with container ships first in the clearance and lock queues
    template          every hook, documented, doing what the baseline does: copy it to start a new strategy
    local_lookahead   S1: each resource on its own with a short look-ahead (docs/strategies/port_management_strategies.md)
    chain_planning    S2: the call chain in step: departures first, clearance whenever the resources are free,
                      just-in-time speeds to the lock entry for sea-going ships and inland craft
    equilibrium_guidance   S3: an approximate Nash equilibrium of the ships' guidance game each round (PULSE)
    evolutionary_guidance  S4: the same game searched by a genetic algorithm on perturbed futures

Modules whose name starts with "_" are helpers, not strategies (_common: shared estimators, _games: game solvers).

A run names its strategy: Simulation(vts="baseline"), pipeline.py --vts baseline. Besides the names of the modules
here, a strategy can be given as "package.module:Class" or "path/to/file.py:Class" (a strategy kept elsewhere), and
options as a dict (Simulation(vts_options=...), pipeline.py --vts-option key=value), passed to its constructor.
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import pkgutil
from pathlib import Path

from vts_api import Strategy


def available():
    """name -> Strategy class, for every strategy module in this folder."""
    out = {}
    for m in pkgutil.iter_modules([str(Path(__file__).parent)]):
        if m.name.startswith("_"):
            continue
        mod = importlib.import_module(f"strategies.{m.name}")
        for obj in vars(mod).values():
            if (inspect.isclass(obj) and issubclass(obj, Strategy) and obj.__module__ == mod.__name__
                    and obj.name != Strategy.name):
                if obj.name in out and out[obj.name] is not obj:
                    raise ValueError(f"two strategies are named {obj.name!r}: {out[obj.name]} and {obj}")
                out[obj.name] = obj
    return out


def _from_spec(spec):
    where, cls = spec.rsplit(":", 1)
    if where.endswith(".py"):
        path = Path(where).resolve()
        loader = importlib.util.spec_from_file_location(f"vts_strategy_{path.stem}", path)
        if loader is None:
            raise ValueError(f"cannot load a strategy from {path}")
        mod = importlib.util.module_from_spec(loader)
        loader.loader.exec_module(mod)
    else:
        mod = importlib.import_module(where)
    obj = getattr(mod, cls, None)
    if not (inspect.isclass(obj) and issubclass(obj, Strategy)):
        raise ValueError(f"{spec!r} is not a VTS strategy (a subclass of vts_api.Strategy)")
    return obj


def resolve(spec="baseline"):
    """The Strategy class a name or "module:Class" / "file.py:Class" stands for (ValueError if none)."""
    if inspect.isclass(spec) and issubclass(spec, Strategy):
        return spec
    spec = str(spec or "baseline")
    if ":" in spec and not (len(spec) == 2 and spec[1] == ":"):
        return _from_spec(spec)
    found = available()
    if spec not in found:
        raise ValueError(f"unknown VTS strategy {spec!r}; available: {', '.join(sorted(found))}")
    return found[spec]


def load(spec="baseline", options=None):
    """A strategy ready for a run: an instance passes through; a name or spec is built with the options."""
    if isinstance(spec, Strategy):
        return spec
    return resolve(spec)(**(options or {}))
