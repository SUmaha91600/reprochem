# ReproChem agent lessons (skill file)

The agent reads this file at the start of each request and adds lessons at the end.
"Tool lessons" and "Reading lessons" go into the agent prompt. "To review" does not:
a person must move each line to "Reading lessons" or delete it.
The lessons marked [seed] were written by hand. A chemist must check them.

## Tool lessons

- Keep the basis notation of the paper in the card, for example 6-31G(d,p). The compiler converts it to 6-31G** itself. [seed]
- Charge and multiplicity belong to the user's molecule. If the paper does not give them, ask the user. Do not take them from a different molecule. [seed]

## Reading lessons

- In "A/B//C/D", the geometry is optimised with C/D and the final energy uses A/B. For a geometry optimisation, use C/D. [seed]
- wB97X-D, B97-D and wB97X-V include their own dispersion. Do not add D3 to them. [seed]
- D3 and D3(BJ) are two different corrections. Keep "(BJ)", "BJ" or "GD3BJ" when the paper writes it. [seed]
- "Closed-shell" means multiplicity 1. "Gas phase" or "in vacuo" means no solvation: write that, not NOT_FOUND. [seed]
- A benchmark paper tests many functionals. Use the functional of the final results, not each functional that the paper tests. [seed]
- The B3LYP of Gaussian is not exactly the B3LYP of PySCF. Keep "B3LYP" in the card: the v1 compiler does not accept B3LYPG. [seed]

## To review

