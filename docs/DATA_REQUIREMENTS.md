# Data specification — wheat and rice disease models

**For:** whoever sources, shoots or labels the images.
**Scope:** two independent models, one per crop. The farmer selects the crop in the app before
photographing, so neither model ever has to tell wheat from rice. Each only has to separate the
diseases *within* its own crop.

Build the dataset to this specification and the model follows. Skip §3 and no amount of training
will help.

---

## 1. Decide the class list first

Every class costs data — roughly 600 images — so a class earns its place or it is dropped. Three
tests, all of which must pass:

**a. Is it visible on a leaf?**
The farmer photographs a leaf. A disease of the grain, the head, the stem base or the root
cannot appear in that photograph, and a model asked to diagnose one can only guess. Exclude
those outright, however economically important they are. They need a different product.

**b. Is it economically worth diagnosing here?**
Prioritise what actually costs Pakistani farmers yield. A disease that is rare locally is not
worth 600 images and a slot in the class list.

**c. Can a trained human tell it apart from the others from a single photograph?**
If an agronomist needs a lab test, a hand lens, or a look at the whole plant, the model will not
manage from one phone picture. Either merge it with a look-alike class or drop it.

### Proposed starting lists

**Confirm both with an agronomist before collecting anything.** These are a starting point based
on leaf visibility and general prevalence, not a final agronomic judgement.

**Wheat**

| Class | Notes |
|---|---|
| yellow (stripe) rust | Usually the priority wheat disease in Pakistan |
| brown (leaf) rust | Confirm it is separable from yellow rust in photographs |
| powdery mildew | Distinctive white growth; usually easy |
| septoria / leaf blotch | Confirm whether septoria and spot blotch are one class or two |
| healthy | |

**Rice**

| Class | Notes |
|---|---|
| bacterial leaf blight | Major in Pakistan |
| leaf blast | |
| brown spot | |
| narrow brown leaf spot | Confirm it is separable from brown spot; merge if not |
| healthy | |

**Ask the agronomist these specifically:**

- Which wheat and rice diseases appear on the **leaf blade**, as opposed to the sheath, stem,
  head or grain? Anything not on the blade is excluded.
- **Sheath diseases** (rice sheath blight, for example) — will a farmer photographing a leaf
  blade actually capture it? If not, it is excluded on the same grounds.
- Which pairs **look alike in a photograph**? Merge them into one class rather than asking the
  model to split what a human cannot.
- Are there diseases missing from these lists that matter more than anything on them?

**Start with 5 or 6 classes per crop, not 9.** Fewer classes with 600 good images each beats
more classes with 150. You can add classes later; you cannot un-spend a season of collection.

---

## 2. How many images

Counts are of **real, distinct** photographs — after de-duplication, before any augmentation.

| | Per class |
|---|---|
| Absolute minimum | **300** |
| Target | **600** |
| Comfortable | **800+** |

**Balance matters as much as the total.** No class should have fewer than half the images of the
largest class in the same crop. A four-fold imbalance means the small classes get ignored, and
those are usually the ones you most wanted.

For 6 classes per crop at the target, that is roughly **3,600 images per crop, 7,200 in total.**
Plan the collection around that number.

---

## 3. Every class needs at least two independent sources

**This is the rule that decides whether the project works.** If you follow nothing else here,
follow this.

"Independent" means a genuinely different origin — a different district, a different season, a
different photographer, a different dataset. Not a different folder in the same download.

- **Minimum 2 sources per class. Target 3.**
- **No single source may supply more than 60% of any class.**

Why it matters: with one source, every image of a disease shares the same camera, the same
lighting, the same background, the same framing. The model learns that shared style instead of
the disease — it is a far easier pattern to find — and then fails completely on any photograph
taken elsewhere. You cannot detect this from the training metrics, because your test set has the
same style. The accuracy looks excellent right up until a farmer uses it.

**A class with only one source cannot be validated.** Its accuracy is unmeasurable at any point
in the project. Do not ship it.

---

## 4. Original images only

Reject any source whose folders are named `_AUG`, `augmented`, `rotated`, `enhanced`, or which
plainly contains near-copies of the same leaf. If a set offers both an original and an augmented
version, take the original.

Augmentation belongs in the training code, applied after the data is split. Augmented copies
sitting in the files on disk defeat every duplicate check — rotation and colour shifts change an
image enough that hashing no longer matches it — so copies of one leaf end up on both sides of
your split. The model then scores brilliantly on images it has effectively already seen.

---

## 5. What each photograph must look like

The model will be used on a farmer's phone, in a field, in daylight. Train it on that.

| Property | Requirement |
|---|---|
| Camera | Phone cameras, including cheap handsets. Not DSLRs. |
| Leaf | **Attached to the living plant** — never detached on paper or a white sheet |
| Background | Cluttered and natural: soil, other leaves, stems, sky, hands |
| Lighting | Natural daylight. Vary it: morning, midday, overcast, light shade |
| Distance | Mixed — close-ups of lesions **and** whole-leaf framing |
| Severity | Early, mid and late stage of each disease |
| Angle | Varied, including tilted and slightly off-centre |
| Focus | Mostly sharp, but keep some imperfect shots — farmers take those |

**At least 60% of every class must be field photographs.** Laboratory or studio images may make
up the rest, no more.

Do not collect only textbook-perfect examples. A model trained on ideal photographs answers
confidently and wrongly on ordinary ones.

### Field shooting protocol

For each diseased plant found:

1. One whole-leaf shot, leaf filling most of the frame
2. One close-up of the lesions
3. One shot from a different angle or in different light
4. Record the `group_id` (§6) so all three stay together

Three shots per plant, from many plants, beats thirty shots of one plant.

---

## 6. Record this for every image

Without these fields a correct split is impossible. One CSV alongside the images is enough.

| Field | Why |
|---|---|
| `source` | District, batch or dataset name. **The split is grouped on this.** |
| `group_id` | Identifies one plant or one photo session. Several shots of the same leaf must never be split across train and test. |
| `crop` | wheat or rice |
| `disease` | the class label |
| `label_verified_by` | who confirmed it, and how |
| `date` | collection date |
| `location` | district, or coordinates if available |
| `severity` | early / mid / late |

`source` and `group_id` cannot be reconstructed afterwards. Capture them at collection time or
they are gone permanently.

---

## 7. Labelling

A wrong label is worse than a missing image: it teaches the model something false and then
punishes it at test time for being right.

- Every class must be confirmed by someone qualified — an agronomist or plant pathologist.
- Have a **second person independently re-label a 10% sample.** If they disagree with the first
  labeller on more than 1 in 10, stop and resolve it before collecting more.
- Record who verified each image in `label_verified_by`.
- If a photograph is ambiguous, **discard it.** Do not guess. An uncertain label pollutes both
  training and evaluation.
- Watch for whole classes that a labeller found difficult — that is a sign the class fails test
  (c) in §1 and should be merged or dropped.

---

## 8. Splitting the data

**Group the split by `source` and `group_id`. Never split randomly.**

A random split puts different photographs of the same leaf, and photographs sharing a style, on
both sides. The test score then measures recall of things already seen, and reads far higher
than reality — typically by tens of points.

Suggested: 70% train, 15% validation, 15% test, **allocated by group, not by image**. All
photographs sharing a `group_id` go to the same side. Where a class has enough sources, hold
back an entire source for testing.

---

## 9. Hold back a real test set

Collect a test set **independently** of everything used for training — a different district, a
different season, ideally a different photographer.

- **50–100 images per class**
- Field conditions and phone cameras, exactly as §5
- Includes healthy leaves
- Never used for training, tuning, early stopping, or choosing between models. Measured once per
  candidate.

This is the only number that predicts field performance. It will read lower than your validation
score. That is the measurement working correctly, not the model failing — and a lower honest
number is worth more than a higher dishonest one.

---

## 10. Healthy leaves

Both models need a healthy class, and it has a trap: collect it **under identical conditions to
the diseased classes.** Same districts, same phones, same photographers, same season.

If healthy images come from somewhere else, the model learns to recognise that source rather
than the health of the plant, and will call every unfamiliar photograph diseased.

**Target 600 healthy images per crop, from at least 2 sources.**

Then measure the false-alarm rate on healthy plants explicitly. Telling a farmer their healthy
crop is diseased costs them money on spray they never needed, and costs you their trust — it is
the most damaging mistake this product can make.

---

## 11. Optional but valuable: a rejection set

Collect **200–300 photographs that are not a diseased leaf of the target crop**: soil, hands,
sky, other plants, blurred nothing, indoor scenes.

Farmers will photograph these. Without them the model has no concept of "this is not a leaf" and
will answer confidently anyway. Use them either as an explicit "not a leaf" class or as a
calibration set for the confidence threshold.

---

## 12. Checklist before training

- [ ] Class list confirmed with an agronomist; every class visible on a leaf blade
- [ ] 5–6 classes per crop, not more
- [ ] ≥300 real images per class, 600 target
- [ ] **≥2 independent sources per class, none over 60%**
- [ ] No pre-augmented images anywhere
- [ ] ≥60% field conditions, phone cameras, leaf attached to the plant
- [ ] Healthy class collected under the same conditions as the diseased ones
- [ ] `source` and `group_id` recorded for every image
- [ ] 10% of labels independently re-checked, disagreement under 10%
- [ ] Split grouped by `source` and `group_id` — never random
- [ ] Independent field test set held back, 50–100 per class
- [ ] Rejection set collected (optional)

---

## 13. What good looks like

Judge every number on the **held-out field test set** from §9, never on validation.

| Measure | Target |
|---|---|
| Top-1 accuracy, per crop | **65%+** |
| Correct disease within the top 3 shown | **85%+** |
| False alarms on healthy leaves | **under 10%** |
| Weakest class | no class below 50% |

Two cautions when reading those:

**A top-3 score means little if the crop has few classes.** With 5 classes, showing 3 hits 60%
by chance alone. Always compare the top-3 figure against `3 ÷ number of classes`, and judge the
margin rather than the raw number.

**If your test score is above 95%, something is wrong with the split.** Check for grouping
failures and augmented duplicates before celebrating. An honest field score in the 60s or 70s is
a working model; a 97% that came from a leaky split is not.
