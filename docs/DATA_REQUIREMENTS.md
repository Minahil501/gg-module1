# Data requirements — wheat & rice specialist model

**For:** whoever sources or photographs the images.
**Purpose:** the wheat and rice classes in the current model do not work in the field. This
document says exactly what data would fix that, and what data would waste your time.

---

## 1. Why this is needed

The shipped model scores **97% on its own test set and 34% on real photographs** for both wheat
and rice. That gap is not bad luck and it is not a shortage of images — rice has ~420 images per
class, more than cotton, which works fine.

The cause is that **every rice class came from one source folder, and that folder was already
augmented.** Zoomed, rotated and colour-shifted copies of the same leaf ended up in both the
training and the test split, because duplicate-detection cannot see through those changes. The
model learned *"photographs that look like that collection"* rather than *"what the disease looks
like"*, and the test set rewarded it for doing so.

The clearest symptom: `wheat_leaf_blight` scores **F1 = 1.00** on the held-out test and was
predicted **zero times** across 80 real wheat photographs. A disease cannot be both perfectly
learned and completely unrecognisable. What was learned was the dataset, not the disease.

**Everything below follows from that one failure.** The single most important rule is rule 1.

---

## 2. What the specialist will cover

The farmer selects the crop before photographing, so this model only ever has to separate
diseases *within* one cereal. Target class list:

| Crop | Classes |
|---|---|
| Wheat | yellow rust, brown rust, septoria, powdery mildew, blast, healthy |
| Rice | bacterial blight, brown spot, leaf blast, leaf scald, sheath blight, healthy |

**Deliberately excluded — do not collect these:**

| Class | Why |
|---|---|
| wheat black point | Affects the **grain**. Not visible on a leaf. Already suppressed in the live service. |
| wheat fusarium foot rot | Affects the **stem base**. Not visible on a leaf. Already suppressed. |

**Verify with an agronomist before collecting** (see §8): `wheat leaf blight` and
`rice sheath blight`.

---

## 3. The three rules that matter most

### Rule 1 — Every class needs at least two independent sources

This is the rule that was broken, and it is worth more than any other on this page.

"Independent" means genuinely different origin: a different dataset, a different field, a
different season, a different photographer. Not a different folder in the same download.

- **Minimum: 2 sources per class.** Target 3.
- **No single source may supply more than 60% of a class.**
- If a class can only be obtained from one source, **it cannot be validated** — its accuracy
  is unmeasurable, and it should not be offered to farmers.

Without this, you cannot build an honest test set, and the model has no reason to learn the
disease rather than the photo style.

### Rule 2 — Original images only. Never pre-augmented.

Reject any dataset whose folders are named `_AUG`, `augmented`, `rotated`, `enhanced`, or which
contains obvious near-copies of the same leaf. If a set has both an original and an augmented
version, **take the original**.

Augmentation belongs in the training pipeline, where it is applied after the split and cannot
leak across it. Augmentation baked into the files on disk defeats every duplicate check and is
precisely what broke rice.

### Rule 3 — Field photographs, not laboratory photographs

A detached leaf on a white sheet teaches the model nothing that survives contact with a farmer's
phone. Required properties:

| Property | Required |
|---|---|
| Camera | Phone camera, including low-end handsets |
| Leaf | **Attached to the living plant** |
| Background | Cluttered — soil, other leaves, stems, sky, hands |
| Lighting | Natural daylight; vary morning / midday / overcast |
| Distance | Mixed: close-ups of lesions *and* whole-leaf framing |
| Severity | Early, mid and late stage of the same disease |
| Angle | Varied, including slightly off-centre and tilted |

At least **60% of every class must be field photographs.** Laboratory images may make up the
remainder, no more.

---

## 4. How many images

Counts are of **real, distinct** photographs — after removing duplicates, before any
augmentation.

| | Per class | Notes |
|---|---|---|
| Absolute minimum | **300** | below this a class is not trainable to a useful standard |
| Target | **600** | |
| Comfortable | **800+** | |

Additional constraints:

- **Balance across classes matters more than raw totals.** No class should have fewer than half
  the images of the largest class in the same crop. Current wheat runs 90 to 390 — over
  four-fold, and the smallest classes are the weakest performers.
- **Priority classes**, currently the thinnest or worst-performing:

| Class | Have | Need | Why |
|---|---|---|---|
| wheat brown rust | 90 | +400 | smallest wheat class |
| wheat powdery mildew | 113 | +400 | weakest working wheat class (30%) |
| wheat leaf blight | 199 | replace entirely | 0% in the field; see §8 |
| wheat blast | 163 | +300 | thin |
| **all six rice classes** | ~420 each | **+300 each, from a different source** | single-source; count is not the problem, origin is |

For rice the instruction is **not "collect more"** — it is "collect *elsewhere*". Another 400
images from the same folder would change nothing.

---

## 5. Healthy leaves are not optional

Both crops need a healthy class collected under **identical conditions** to the diseased ones —
same fields, same phones, same lighting, same photographers.

If healthy images come from a different source than the diseased ones, the model learns to spot
the source rather than the health of the plant, and will call any unfamiliar photograph
diseased.

**Target: 600 healthy images per crop, from at least 2 sources.**

This matters more than it looks. The current model has never been tested on a healthy leaf at
all, so how often it tells a farmer their healthy plant is diseased is completely unknown — and
that is the most damaging mistake this product can make.

---

## 6. Record this for every image

Without these fields a correct train/test split is impossible. A single CSV alongside the images
is enough.

| Field | Why it is needed |
|---|---|
| `source` | Dataset name or collection batch. **The split is grouped on this.** |
| `group_id` | Identifies the same leaf / plant / session. Several photographs of one leaf must never be split across train and test. |
| `crop` | wheat or rice |
| `disease` | class label |
| `label_verified_by` | who confirmed it, and how (see §8) |
| `date` | collection date |
| `location` | district or coordinates, where known |
| `severity` | early / mid / late, if assessable |

`source` and `group_id` are the two that cannot be reconstructed later. Capture them at
collection time or they are lost.

---

## 7. A separate field test set

Hold back a test set **collected independently** of all training data — different fields or a
different season, never used for training or for choosing a model.

- **50–100 images per class.**
- Field conditions, phone cameras, exactly as §3.
- Never used for tuning anything. Measured once per candidate model.

This is the only number that will predict real performance. Expect it to read far lower than
your current 97%, and treat that as the measurement working rather than the model failing.

The existing `named.zip` (508 web photographs) can serve as an interim benchmark, but it is
web-sourced rather than farmer-sourced and contains no healthy leaves.

---

## 8. Verify these with an agronomist before spending money

**`wheat leaf blight` — 199 images, perfect on the held-out test, predicted zero times in the
field.** Before collecting a single new image, open 20 of the existing ones and have someone
qualified confirm they show wheat leaf blight at all. A whole class scoring 0% in the wild very
often means the label is wrong, not that the model is weak. This is a ten-minute check that may
save weeks.

**`rice sheath blight` — check it is diagnosable from a leaf photograph.** Sheath blight begins
on the leaf *sheath* and spreads to the blade. If a farmer photographing a leaf blade will
usually miss it, it belongs with wheat black point in the excluded list — a disease the model
can only ever guess at. Note that the current model over-predicts this class heavily: it
answered "sheath blight" 34 times out of 65 rice photographs.

**Confirm the split between `wheat blast` and `rice leaf blast`.** Both are caused by related
*Magnaporthe* pathogens and can look alike; since the crop is always supplied, they never
compete, but their labels should still be consistent.

---

## 9. Sources worth investigating

**Verify each yourself before relying on it** — licence, provenance, and whether the images are
originals rather than augmented copies.

| Crop | Worth checking |
|---|---|
| Rice | Mendeley *Rice Leaf Disease Image Samples* (Sethy et al.); *Dhan-Shomadhan* (Bangladeshi field rice) |
| Wheat | CGIAR wheat rust dataset (Zindi / ICLR crop-disease challenge) — field photography of rust |
| Both | PlantDoc — field images, already partly in use |

**Your own field collection is worth more than any of these.** Images from Pakistani fields, on
the handsets farmers actually own, match deployment conditions exactly — which is the entire
problem this document exists to solve. A single season of collection across a few districts
would outweigh every dataset listed above.

---

## 10. Checklist before training

- [ ] Every class has ≥2 independent sources, none supplying >60%
- [ ] No pre-augmented images anywhere in the training data
- [ ] ≥300 real images per class; ≥60% field conditions
- [ ] Healthy class for both crops, same conditions as the diseased classes
- [ ] `source` and `group_id` recorded for every image
- [ ] Split grouped by `source` and `group_id` — **never random**
- [ ] Independent field test set held back, 50–100 per class
- [ ] `wheat leaf blight` labels checked by an agronomist
- [ ] `rice sheath blight` confirmed diagnosable from a leaf photograph
- [ ] wheat black point and fusarium foot rot excluded

If the first and last boxes are the only ones you manage, you will still be substantially ahead
of where this model stands today.

---

## 11. What "good" will look like

Do not expect 97% again. That number came from a test set measuring memorisation, and an honest
test set will never produce it.

Realistic targets on a proper field test set, against what the current model achieves:

| | Now | Target |
|---|---|---|
| Wheat top-1 | 42% | 65%+ |
| Rice top-1 | 34% | 65%+ |
| Correct disease in the top 3 | 63% / 62% | 85%+ |

For comparison, maize and cotton reach 73% top-1 and 93–96% top-3 on the same web photographs —
so those targets are what this data pipeline already achieves for crops that have more than one
source. That is the bar, and it is reachable.
