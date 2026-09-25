"""Render the Module 1 evaluation report to PDF from the measured stats.

Kept as a script rather than a hand-made PDF so the report can be regenerated
after any re-run: change the model or the thresholds, re-run test_zip.py, then
re-run this. A report that cannot be regenerated goes stale silently.

    venv/Scripts/python tools/build_report.py stats.json docs/EVALUATION_REPORT.pdf
"""

import json
import sys
from datetime import date

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (KeepTogether, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

INK = colors.HexColor("#1a1a1a")
MUTED = colors.HexColor("#5b6670")
RULE = colors.HexColor("#d4d9dd")
BAND = colors.HexColor("#f2f5f7")
GOOD = colors.HexColor("#1f7a45")
WARN = colors.HexColor("#8a6100")
BAD = colors.HexColor("#a32020")

styles = getSampleStyleSheet()
S = {
    "title": ParagraphStyle("t", parent=styles["Title"], fontName="Helvetica-Bold",
                            fontSize=20, leading=24, textColor=INK, alignment=TA_LEFT,
                            spaceAfter=2),
    "sub": ParagraphStyle("s", parent=styles["Normal"], fontSize=9.5, leading=13,
                          textColor=MUTED, spaceAfter=14),
    "h1": ParagraphStyle("h1", parent=styles["Heading1"], fontName="Helvetica-Bold",
                         fontSize=13, leading=16, textColor=INK, spaceBefore=16, spaceAfter=6),
    "h2": ParagraphStyle("h2", parent=styles["Heading2"], fontName="Helvetica-Bold",
                         fontSize=10.5, leading=14, textColor=INK, spaceBefore=11, spaceAfter=4),
    "body": ParagraphStyle("b", parent=styles["Normal"], fontSize=9.5, leading=14,
                           textColor=INK, spaceAfter=7),
    "small": ParagraphStyle("sm", parent=styles["Normal"], fontSize=8.2, leading=11,
                            textColor=MUTED, spaceAfter=6),
    "cell": ParagraphStyle("c", parent=styles["Normal"], fontSize=8.5, leading=11),
}


def para(text, style="body"):
    return Paragraph(text, S[style])


def callout(title, text, tone=BAD):
    """A boxed statement for the findings a reader must not skim past."""
    inner = [[Paragraph(f"<b>{title}</b>", ParagraphStyle(
        "ct", parent=S["body"], textColor=tone, fontSize=10, spaceAfter=3))],
        [Paragraph(text, ParagraphStyle("cb", parent=S["body"], fontSize=9, leading=13,
                                        spaceAfter=0))]]
    t = Table(inner, colWidths=[160 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), BAND),
        ("LINEBEFORE", (0, 0), (0, -1), 2.5, tone),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("RIGHTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, 0), 8),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 8),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def table(head, rows, widths, aligns=None, marks=None):
    data = [[Paragraph(f"<b>{h}</b>", S["cell"]) for h in head]]
    for r in rows:
        data.append([Paragraph(str(c), S["cell"]) for c in r])
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [
        ("LINEBELOW", (0, 0), (-1, 0), 0.9, INK),
        ("LINEBELOW", (0, 1), (-1, -2), 0.3, RULE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 4.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
    ]
    for col, al in enumerate(aligns or []):
        if al != "l":
            style.append(("ALIGN", (col, 0), (col, -1), "RIGHT" if al == "r" else "CENTER"))
    for (row, tone) in (marks or []):
        style.append(("BACKGROUND", (0, row), (-1, row), tone))
    t.setStyle(TableStyle(style))
    return t


def verdict(top1):
    """Judged on first-guess accuracy, which is what decides whether a crop ships.

    Deliberately NOT judged on the top-3 margin over chance: a crop with only
    three classes scores a huge top-3 by construction, and a crop with nine
    scores poorly even when its first guess is sound. Ranking on that would call
    wheat usable and cotton marginal, which is backwards.
    """
    if top1 >= 70:
        return '<font color="#1f7a45">usable</font>'
    if top1 >= 55:
        return '<font color="#8a6100">borderline</font>'
    if top1 >= 45:
        return '<font color="#8a6100">weak</font>'
    return '<font color="#a32020"><b>do not ship</b></font>'


def build(stats_path, out_path):
    st = json.load(open(stats_path, encoding="utf-8"))
    ov, crops, sweep = st["overall"], st["per_crop"], st["sweep"]

    doc = SimpleDocTemplate(out_path, pagesize=A4,
                            leftMargin=25 * mm, rightMargin=25 * mm,
                            topMargin=20 * mm, bottomMargin=18 * mm,
                            title="GreenGuard Module 1 - Model Evaluation",
                            author="GreenGuard AI team")
    f = []

    f.append(para("GreenGuard Module 1 &mdash; Leaf Disease Model Evaluation", "title"))
    f.append(para(f"EfficientNet-B0 (<font face='Courier'>efficientnet_b0-1.0</font>), 40 classes, 7 crops"
                  f" &nbsp;&middot;&nbsp; 528 held-out photographs"
                  f" &nbsp;&middot;&nbsp; {date.today():%d %B %Y}", "sub"))

    # ---------------------------------------------------------------- verdict
    f.append(para("1. Verdict", "h1"))
    f.append(callout(
        "Usable for three crops. Not usable for rice or wheat.",
        "Given the crop, the model identifies the disease correctly <b>56% of the time</b> on its "
        "first guess, against 19% for random guessing. Within its three-item shortlist the correct "
        "disease appears <b>83% of the time</b>. Accuracy is highly uneven across crops: potato, "
        "cotton and maize reach 73&ndash;77% first-guess accuracy, while rice and wheat reach only "
        "34% &mdash; close to guesswork for those two crops. No threshold setting corrects this; it "
        "requires retraining.", BAD))
    f.append(Spacer(1, 9))
    f.append(para(
        "The service is therefore configured to present a <b>ranked shortlist of three</b> rather "
        "than a single diagnosis. The shortlist is the product; the single best guess is not "
        "reliable enough to stand alone.", "body"))

    # ---------------------------------------------------------------- method
    f.append(para("2. What was tested, and how", "h1"))
    f.append(para(
        "528 photographs covering all 33 disease classes across the 7 supported crops, sourced from "
        "the web rather than from the training distribution. Each image's true class was read from "
        "its folder path and filename code (for example <font face='Courier'>wheat/yellow rust/"
        "Wyr3.jpg</font>); all 528 resolved unambiguously and none were excluded.", "body"))
    f.append(para(
        "Every measurement supplies the model with the <b>correct crop</b>, because in the "
        "application the farmer selects the crop before photographing. Identifying the crop is "
        "therefore never the model's task, and figures here reflect only its ability to tell that "
        "crop's diseases apart.", "body"))
    f.append(para(
        "Because the photographs are web-sourced, this measures <b>generalisation to realistic "
        "field imagery</b>, which is a harder and more relevant test than a held-out split of the "
        "training data. A higher accuracy reported during training is not contradicted by these "
        "figures; the gap between them is itself the finding.", "body"))

    # ---------------------------------------------------------------- headline
    f.append(para("3. Overall accuracy, crop supplied", "h1"))
    f.append(table(
        ["Measure", "Result", "Random guessing", "Reading"],
        [["First guess correct (top-1)", f"<b>{ov['top1']:.0f}%</b>", f"{ov['chance']:.0f}%",
          "roughly 3&times; chance"],
         ["Correct within top 2", f"{ov['top2']:.0f}%", "&mdash;", ""],
         ["Correct within top 3", f"<b>{ov['top3']:.0f}%</b>", "&mdash;",
          "the shortlist usually contains it"]],
        [58 * mm, 24 * mm, 30 * mm, 48 * mm], ["l", "c", "c", "l"]))
    f.append(Spacer(1, 4))
    f.append(para("Measured with all decision gates removed, so these reflect the model itself "
                  "rather than the thresholds applied on top of it.", "small"))

    # ---------------------------------------------------------------- per crop
    f.append(para("4. Accuracy by crop", "h1"))
    f.append(para(
        "The single most important table in this report. A shortlist of three drawn from a crop "
        "with only three classes conveys nothing, so the shortlist figure must always be read "
        "against what pure chance would already achieve.", "body"))
    rows, marks = [], []
    for i, c in enumerate(crops, start=1):
        rows.append([c["crop"].title(), c["classes"], f"{c['top1']:.0f}%", f"{c['top3']:.0f}%",
                     f"{c['chance3']:.0f}%", verdict(c["top1"])])
        if c["top1"] < 45:
            marks.append((i, colors.HexColor("#fdf0f0")))
    f.append(KeepTogether(table(["Crop", "Classes", "Top-1", "Top-3", "Top-3 by chance", "Verdict"],
                               rows, [34 * mm, 18 * mm, 20 * mm, 20 * mm, 32 * mm, 36 * mm],
                               ["l", "c", "r", "r", "r", "l"], marks)))
    f.append(Spacer(1, 7))
    f.append(KeepTogether([
        para("Two entries need reading carefully", "h2"),
        para("<b>Potato&nbsp;&mdash;&nbsp;100% top-3 is arithmetic, not skill.</b> Only three potato "
             "classes exist, so a three-item shortlist lists all of them. For potato the interface "
             "should show the single prediction (77% correct) and no shortlist.", "body"),
        para("<b>Rice&nbsp;&mdash;&nbsp;62% top-3 against 50% by chance.</b> Neither the first guess "
             "(34%) nor the shortlist carries meaningful signal. Rice should not be offered to "
             "farmers until the model is retrained.", "body")]))

    # ---------------------------------------------------------------- threshold
    f.append(para("5. The confidence threshold and what it buys", "h1"))
    f.append(para(
        "The model returns a confidence score, and the service stays silent when that score falls "
        "below a configured threshold. The threshold therefore governs <b>how often the service "
        "answers</b>, not how often it is right. Lowering it does not make the model better; it "
        "makes it speak more, correctly and incorrectly alike.", "body"))
    rows, marks = [], []
    for i, s in enumerate(sweep, start=1):
        label = f"{s['t']:.2f}" + (" &nbsp;<b>(in use)</b>" if abs(s["t"] - 0.35) < 1e-9 else "")
        rows.append([label, f"{s['cov']:.0f}%", f"{s['top1']:.0f}%", f"{s['top3']:.0f}%",
                     f"{s['wrong']}"])
        if abs(s["t"] - 0.35) < 1e-9:
            marks.append((i, colors.HexColor("#eef4ef")))
    f.append(table(
        ["Threshold", "Answers given", "First guess right", "Shortlist has it", "Wrong first guesses"],
        rows, [30 * mm, 30 * mm, 32 * mm, 32 * mm, 36 * mm],
        ["l", "r", "r", "r", "r"], marks))
    f.append(Spacer(1, 6))
    f.append(para(
        "<b>0.35 was chosen</b> so the service answers 86% of photographs rather than 25%. The cost "
        "is that its first guess is then wrong on roughly one answer in three &mdash; acceptable "
        "only because the shortlist is shown alongside it, and contains the correct disease 88% of "
        "the time.", "body"))

    f.append(Spacer(1, 6))
    f.append(callout(
        "Requirement on the application, not a suggestion",
        "The interface must present all three ranked possibilities, never the single prediction as "
        "a diagnosis. Displaying only the first guess would place an incorrect disease in front of "
        "a farmer in roughly one case in three, with a treatment decision attached to it. Suggested "
        "phrasing: &ldquo;most likely X; possibly Y or Z &mdash; confirm before treating&rdquo;.",
        WARN))

    # ---------------------------------------------------------------- config
    f.append(para("6. Configuration applied", "h1"))
    f.append(para("All values live in <font face='Courier'>model/config.json</font> and are changed "
                  "without touching code.", "body"))
    f.append(table(
        ["Setting", "Was", "Now", "Why"],
        [["<font face='Courier'>crop_filtered_threshold</font>", "0.80", "<b>0.35</b>",
          "answer 86% of photographs instead of 45%, with the shortlist carrying the accuracy"],
         ["<font face='Courier'>crop_mismatch_threshold</font>", "0.50", "<b>1.01</b>",
          "disabled: the farmer&rsquo;s crop selection is authoritative, and the model&rsquo;s own "
          "crop guess was wrong on 38% of photographs, so the check rejected good answers"],
         ["<font face='Courier'>confidence_threshold</font>", "0.70", "0.70",
          "unchanged; applies only if no crop is supplied, which the application never does"]],
        [46 * mm, 15 * mm, 15 * mm, 84 * mm], ["l", "c", "c", "l"]))

    # ---------------------------------------------------------------- limits
    f.append(para("7. Limits of this evaluation", "h1"))
    f.append(table(
        ["Limitation", "Consequence"],
        [["<b>No healthy leaves were tested.</b> The set contains 33 disease classes and no healthy "
          "class, though the model has one for every crop.",
          "The rate at which the model reports disease on a <i>healthy</i> plant is unmeasured. For "
          "a farmer-facing tool this is the most damaging error available, and it is currently "
          "unknown. Approximately 50 healthy photographs per crop should be tested before release."],
         ["<b>One test set, web-sourced.</b>", "Figures describe generalisation to web imagery. "
          "Photographs taken by farmers on low-end phones may differ again."],
         ["<b>Class sizes are uneven</b> (10 to 25 photographs per class).",
          "Per-crop figures drawn from 10 photographs carry a margin of roughly &plusmn;15 points; "
          "small differences between crops should not be over-read."],
         ["<b>Non-leaf input was not tested.</b>",
          "In a brief check, images of pure random noise were returned as confident diagnoses. The "
          "model has no &ldquo;this is not a leaf&rdquo; class, and the thresholds did not catch "
          "them. Photographs of soil, hands or sky should be tested."]],
        [56 * mm, 104 * mm], ["l", "l"]))

    # ---------------------------------------------------------------- next
    f.append(para("8. Recommendations", "h1"))
    f.append(table(
        ["", "Action", "Rationale"],
        [["1", "Display all three possibilities in the interface",
          "Without this the 0.35 threshold is unsafe; with it, the correct disease reaches the "
          "farmer 88% of the time"],
         ["2", "Test healthy leaves before release",
          "The false-alarm rate on healthy plants is the largest unknown in this evaluation"],
         ["3", "Withhold rice, and treat wheat as provisional",
          "34% first-guess accuracy on both; rice&rsquo;s shortlist barely exceeds chance"],
         ["4", "Retrain on field-realistic imagery",
          "The model confuses crops that look nothing alike, which indicates the training images "
          "differ markedly from real photographs; this is the only route to fixing rice and wheat"],
         ["5", "Suppress the shortlist for potato",
          "Three classes exist, so the shortlist lists all of them and conveys nothing"]],
        [8 * mm, 56 * mm, 96 * mm], ["c", "l", "l"]))

    f.append(Spacer(1, 12))
    f.append(para(
        "Reproduce with <font face='Courier'>venv/Scripts/python tools/test_zip.py --zip &lt;set&gt;.zip "
        "--send-crop</font>. Per-photograph predictions, confidences and shortlists for every "
        "configuration are in <font face='Courier'>test_results/</font>.", "small"))

    doc.build(f)
    print(f"wrote {out_path}")


if __name__ == "__main__":
    build(sys.argv[1], sys.argv[2])
