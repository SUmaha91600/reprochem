"""Five real requests a chemist would send to the ReproChem agent (S1 agent sheet).

ReproChem extracts the 7 computational fields of a quantum-chemistry protocol
(functional, basis set, dispersion, solvation, charge, multiplicity, software) from
papers and internal documents, then compiles them into runnable calculations.
"""
from workflow_or_agent import Request

REQUESTS = [
    Request(
        text="Read the Computational Details of this PDF and give me the 7 fields "
             "(functional, basis set, dispersion, solvation, charge, multiplicity, software) as JSON.",
        steps_unknown=False, needs_tools=True, cheap_mistakes=True, afford_cost=True, auto_check=True,
        decision="workflow", pattern="prompt chaining",
        justification="The path never changes (find the methods section, extract into a strict schema, "
                      "flag empty fields), so code fixes the steps and the gold-annotated papers check the output."),
    Request(
        text="Turn this protocol (wB97X-D/def2-TZVP, SMD water, charge 0, singlet, Gaussian 16) "
             "into a ready-to-run input file for my geometry.",
        steps_unknown=False, needs_tools=True, cheap_mistakes=True, afford_cost=True, auto_check=True,
        decision="workflow", pattern="single compile step + validator",
        justification="Compilation is a deterministic template plus a validator (for example, no extra D3 "
                      "keyword, since wB97X-D already contains its dispersion term), so a loop would only add cost."),
    Request(
        text="For these 20 papers on conformer energies, tell me which ones report all 7 fields "
             "and which ones omit charge, multiplicity or solvation.",
        steps_unknown=False, needs_tools=True, cheap_mistakes=True, afford_cost=True, auto_check=True,
        decision="workflow", pattern="parallelisation",
        justification="It is the same extraction mapped over 20 independent papers and then aggregated, "
                      "which is the parallelisation pattern with a known number of calls."),
    Request(
        text="The paper generated conformers with CREST (GFN2-xTB) and re-optimised the lowest ones at "
             "B3LYP-D3(BJ)/def2-SVP; reproduce the ensemble for my molecule and tell me which conformer "
             "is the global minimum at their level.",
        steps_unknown=True, needs_tools=True, cheap_mistakes=False, afford_cost=True, auto_check=True,
        decision="agent", pattern="agent loop with approval",
        justification="Key details such as the energy window and how many conformers were re-optimised are "
                      "often missing, so the agent must search the SI, decide, run, check convergence and "
                      "imaginary frequencies and retry, with my approval before any cluster job is submitted."),
    Request(
        text="My relative conformer energies differ from Table 2 of the paper by up to 2 kcal/mol; find out why.",
        steps_unknown=True, needs_tools=True, cheap_mistakes=True, afford_cost=True, auto_check=True,
        decision="agent", pattern="read-only diagnosis loop",
        justification="The next check depends on the last result (D3 vs D3(BJ), solvation model, geometry level, "
                      "electronic vs Gibbs energies, temperature), and since it only reads files a wrong step is cheap."),
]
