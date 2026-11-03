"""JobSpec -> runnable PySCF script, then a runnability test.

The project's main metric is computed here: does the generated script run to
convergence on a reduced version of the system?
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
import textwrap

from .schema import JobSpec

TEMPLATE = '''\
# Généré par ReproChem. Ne pas éditer à la main.
from pyscf import gto, dft
{opt_import}

mol = gto.M(
    atom={atom!r},
    basis={basis!r},
    charge={charge},
    spin={spin},
    verbose=0,
)
mf = dft.RKS(mol) if mol.spin == 0 else dft.UKS(mol)
mf.xc = {xc!r}
{dispersion}
{solvent}
mf.conv_tol = {conv_tol}
mf.max_cycle = {max_cycle}
energy = mf.kernel()
{optimise}
print("CONVERGED", mf.converged)
print("ENERGY", energy)
'''


def smiles_to_xyz(smiles: str) -> str:
    """Starting geometry. Uses RDKit if available, otherwise the error propagates."""
    from rdkit import Chem
    from rdkit.Chem import AllChem

    mol = Chem.AddHs(Chem.MolFromSmiles(smiles))
    AllChem.EmbedMolecule(mol, randomSeed=0xC0FFEE)
    AllChem.MMFFOptimizeMolecule(mol)
    conf = mol.GetConformer()
    lines = []
    for atom in mol.GetAtoms():
        p = conf.GetAtomPosition(atom.GetIdx())
        lines.append(f"{atom.GetSymbol()} {p.x:.6f} {p.y:.6f} {p.z:.6f}")
    return "; ".join(lines)


# ── SAFEGUARD S11 · values enter the script as quoted strings (LLM05) ── tested by: C1
#    Every value is inserted with repr(): code inside a value stays an inert string (checked with ast in security_eval.py).
def render(spec: JobSpec, conv_tol: float = 1e-8, max_cycle: int = 60) -> str:
    disp = f'mf.disp = {spec.dispersion.lower()!r}' if spec.dispersion else ""
    solv = ""
    if spec.solvent:
        solv = textwrap.dedent(f"""\
            from pyscf import solvent as _solvent
            mf = mf.PCM()
            mf.with_solvent.method = 'C-PCM'
            mf.with_solvent.eps = {_EPS.get(spec.solvent.lower(), 78.4)}""")
    optimise = ""
    opt_import = ""
    if spec.task == "geometry_optimisation":
        opt_import = "from pyscf.geomopt.geometric_solver import optimize"
        optimise = "mol_eq = optimize(mf, maxsteps=50)"
    return TEMPLATE.format(
        atom=smiles_to_xyz(spec.molecule_smiles),
        basis=spec.basis,
        charge=spec.charge,
        spin=spec.multiplicity - 1,
        xc=spec.functional,
        dispersion=disp,
        solvent=solv,
        conv_tol=conv_tol,
        max_cycle=max_cycle,
        optimise=optimise,
        opt_import=opt_import,
    )


_EPS = {"water": 78.4, "eau": 78.4, "acetonitrile": 35.7, "toluene": 2.38,
        "dmso": 46.7, "methanol": 32.6, "chloroform": 4.71}


def runs(script: str, timeout: int = 300) -> tuple[bool, str]:
    """Runnability: does the script run and converge?"""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as fh:
        fh.write(script)
        path = fh.name
    try:
        proc = subprocess.run([sys.executable, "-I", path], capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, "timeout"
    ok = proc.returncode == 0 and "CONVERGED True" in proc.stdout
    return ok, (proc.stdout + proc.stderr)[-800:]
