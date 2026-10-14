#!/usr/bin/env python3
"""Can this file be copied into that install tree without breaking it?

Copying one fixed module over an older install tree reaches the sessions bound to it without a restart,
which is the only remediation that does not cost one human action per session. On 2026-10-14 it was done
to stop a live context leak in ten trees, and it broke their SessionStart hook: the fixed file had renamed
`watch.last_reasons` to `last_moved`, and those trees keep their own older `hooks.py`, which still calls
the old name.

The pre-flight that missed it asked only whether the NEW file could find what it needs in the OLD tree.
That is half the question. The other half is whether the old tree can still find what it asks for in the
new file -- and that is the half that broke. So this checks both directions and reports each separately:

  inbound   names the new file asks of the tree's other modules, that the tree does not define
  outbound  names the tree's other modules ask of this module, that the new file does not define

Either being non-empty means the graft is unsafe. Both being empty does not make a graft *correct* -- it
makes the interface closed, which is a necessary condition and not a sufficient one. Behaviour coupling
that does not show up as a name is not visible here, so the report also prints the coupling surface: the
names actually crossing the boundary, which is what a human has to reason about.

Reads only; copies nothing.
"""
import argparse
import ast
import os
import sys


def _parse(path):
    try:
        return ast.parse(open(path, encoding="utf-8", errors="replace").read())
    except (OSError, SyntaxError):
        return None


def _defines(path):
    """Top-level names a module provides, including aliases and constants."""
    tree = _parse(path)
    if tree is None:
        return None
    out = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            out.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return out


def _imported_siblings(tree):
    """Sibling module names this file imports, by the name it uses them under.

    Resolving through the imports is what separates a module from a local variable. Matching every
    `Name.attr` instead reported `changes.append` as a missing module attribute, because a sibling had a
    list called `changes` -- a false positive on a check whose whole job is to be trusted.
    """
    names = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level and node.module in (None, "rwlib"):
            for alias in node.names:
                names[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module == "rwlib":
            for alias in node.names:
                names[alias.asname or alias.name] = alias.name
    return names


def _asks(tree, under):
    """Attributes read off the name `under`."""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == under:
            out.add(node.attr)
    return out


def check(new_file, pkg_dir):
    """(inbound_missing, outbound_missing, coupling) for grafting new_file into pkg_dir."""
    name = os.path.basename(new_file)[:-3]
    provides = _defines(new_file)
    tree = _parse(new_file)
    if provides is None or tree is None:
        return None, None, None

    # Inbound: what this file needs from the tree. A module the tree does not have at all is the
    # worst case and must not be skipped -- skipping it reported a graft SAFE when the tree was
    # missing the module the file imports, which is a false clean.
    inbound = []
    for under, mod in sorted(_imported_siblings(tree).items()):
        path = os.path.join(pkg_dir, mod + ".py")
        if not os.path.exists(path):
            inbound.append(f"{mod} (module absent from this tree)")
            continue
        have = _defines(path) or set()
        inbound += [f"{mod}.{a}" for a in sorted(_asks(tree, under)) if a not in have]

    # Outbound: what the tree asks of this module, counted only where the sibling imports it.
    outbound, coupling = [], set()
    for f in sorted(os.listdir(pkg_dir)):
        if not f.endswith(".py") or f == f"{name}.py":
            continue
        sib = _parse(os.path.join(pkg_dir, f))
        if sib is None:
            continue
        for under, mod in _imported_siblings(sib).items():
            if mod != name:
                continue
            asked = _asks(sib, under)
            coupling |= asked
            outbound += [f"{name}.{a}" for a in sorted(asked) if a not in provides]
    return sorted(set(inbound)), sorted(set(outbound)), sorted(coupling)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("new_file", help="the fixed module that would be copied in")
    ap.add_argument("trees", nargs="+", help="package directories to graft it into (e.g. .../scripts/rwlib)")
    args = ap.parse_args(argv)

    worst = 0
    for pkg in args.trees:
        label = pkg
        for part in pkg.split(os.sep):
            if part and part[0].isdigit():
                label = part
                break
        inbound, outbound, coupling = check(args.new_file, pkg)
        if inbound is None:
            print(f"  {label:16} UNREADABLE")
            worst = 2
            continue
        verdict = "SAFE" if not inbound and not outbound else "UNSAFE"
        worst = max(worst, 1 if verdict == "UNSAFE" else 0)
        print(f"  {label:16} {verdict:6} inbound-missing={inbound or '-'} outbound-missing={outbound or '-'}")
        print(f"  {'':16}        coupling surface: {', '.join(coupling) or 'none'}")
    print()
    print("SAFE means the interface is closed in both directions. It is necessary, not sufficient:")
    print("behaviour coupling that is not a name does not appear here -- read the coupling surface.")
    return worst


if __name__ == "__main__":
    sys.exit(main())
