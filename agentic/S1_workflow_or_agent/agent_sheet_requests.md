# ReproChem · Workflow or agent? Five real requests

| # | Request | Decision | Justification (one sentence) | Level | Safeguards | Checklist agrees |
|---|---|---|---|---|---|---|
| 1 | Read the Computational Details of this PDF and give me the 7 fields (functional, basis set, dispersion, solvation, charge, multiplicity, software) as JSON. | **Workflow (prompt chaining)** | The path never changes (find the methods section, extract into a strict schema, flag empty fields), so code fixes the steps and the gold-annotated papers check the output. | 1 · Workflow | none | yes |
| 2 | Turn this protocol (wB97X-D/def2-TZVP, SMD water, charge 0, singlet, Gaussian 16) into a ready-to-run input file for my geometry. | **Workflow (single compile step + validator)** | Compilation is a deterministic template plus a validator (for example, no extra D3 keyword, since wB97X-D already contains its dispersion term), so a loop would only add cost. | 1 · Workflow | none | yes |
| 3 | For these 20 papers on conformer energies, tell me which ones report all 7 fields and which ones omit charge, multiplicity or solvation. | **Workflow (parallelisation)** | It is the same extraction mapped over 20 independent papers and then aggregated, which is the parallelisation pattern with a known number of calls. | 1 · Workflow | none | yes |
| 4 | The paper generated conformers with CREST (GFN2-xTB) and re-optimised the lowest ones at B3LYP-D3(BJ)/def2-SVP; reproduce the ensemble for my molecule and tell me which conformer is the global minimum at their level. | **Agent (agent loop with approval)** | Key details such as the energy window and how many conformers were re-optimised are often missing, so the agent must search the SI, decide, run, check convergence and imaginary frequencies and retry, with my approval before any cluster job is submitted. | 3 · Agent loop | human approval before write or costly actions | yes |
| 5 | My relative conformer energies differ from Table 2 of the paper by up to 2 kcal/mol; find out why. | **Agent (read-only diagnosis loop)** | The next check depends on the last result (D3 vs D3(BJ), solvation model, geometry level, electronic vs Gibbs energies, temperature), and since it only reads files a wrong step is cheap. | 3 · Agent loop | none | yes |

## Checklist answers (S1 deck, "When not to build an agent")

| # | Are the steps unknown until you see the task? | Does it need fresh data or actions in other systems? | Is a wrong step cheap and easy to undo? | Can you afford 10x the cost and latency of one call? | Can you check success automatically? |
|---|---|---|---|---|---|
| 1 | no | yes | yes | yes | yes |
| 2 | no | yes | yes | yes | yes |
| 3 | no | yes | yes | yes | yes |
| 4 | yes | yes | no | yes | yes |
| 5 | yes | yes | yes | yes | yes |
