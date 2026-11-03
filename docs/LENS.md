# ReproChem Lens — explaining by voice, with diagrams

**The idea.** You ask a question out loud. The system answers with a diagram
instead of a paragraph. On request ("… as a video"), it narrates that diagram
in five acts, the voice in sync with the elements as they appear.

```
voice → recognition → intent router ─┬─ known concept   → animated diagram
                                     ├─ "as a video"    → 5 narrated acts
                                     └─ false premise   → correction, then diagram
```

## What the demo does (`bash scripts/lens.sh`)

- **10 verified concepts**, covering the 7 fields of the card: BP86, B3LYP,
  the ladder of functionals, 6-311++G(d,p) and the basis set families,
  dispersion (D2 → D4), solvation, charge and multiplicity, software
  packages, the anatomy of an optimization, and ReproChem itself.
- **Five acts** per concept: question, problem, elements of the answer,
  answer, going further. The follow-ups in the last act are clickable and
  open the next concept.
- **Premise correction**: "the BP86 basis set" → "BP86 is not a basis set,
  it is a functional", spoken and displayed before the explanation.
- **Interruption**: speaking during the video stops it and handles the new
  question. Space = talk, P = pause, Esc = stop, CC = subtitles.
- **Sources** shown under each diagram (the original papers behind each
  method).

## Design choices

- **The model does not draw.** Each concept is a specification written and
  checked by hand (`app/lens/concepts.js`): placed nodes, links, sources, the
  text of each act. The engine (`app/lens/lens.js`) only displays it and
  syncs it with the voice. This is what keeps the diagrams correct and
  readable.
- **Fixed color code**: cyan = core mechanism, red = limitation,
  green = solution, yellow = result, orange = pitfall, dashed purple =
  follow-up.
- **An unknown concept is never invented**: the system says so and offers the
  list of verified concepts.

## Demo and target version

| | November 3 demo | Target version |
|---|---|---|
| Speech recognition | the browser's own (Web Speech API, needs network) | local Whisper, with VAD and domain vocabulary in the initial prompt |
| Voice | the system's text-to-speech (macOS), flagged as synthetic | Kokoro or Piper, running locally |
| Diagrams | 10 concepts written by hand | the LLM produces a schema-constrained JSON spec, rendered with the same templates, each node sourced through RAG |
| Video | narrated playback in the browser | same, plus MP4 export |

## How to evaluate it

| Question | Measure |
|---|---|
| Are chemistry terms recognized? | WER on 30 dictated questions (B3LYP, def2-TZVP…), with and without injected vocabulary |
| Does the right concept open? | router accuracy on these 30 questions |
| Are false premises caught? | 10 trick questions |
| Is the voice understandable? | WER of an ASR run on the generated voice (method from the November 2 class) |
| Are the diagrams correct? | expert review, share of nodes backed by a source |

## Safety and law

No emotion recognition (banned in schools and workplaces by the AI Act,
Art. 5). The synthetic voice is flagged as such (Art. 50). The demo sends
audio to the browser's speech recognition service, so it must not be used on
confidential documents. That is why the target is local Whisper.
