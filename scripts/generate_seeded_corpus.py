"""Generate the seeded synthetic corpus + QA labels (deterministic).

Produces a small fictional company knowledge base ("Helios Robotics") across
.md / .txt / .html / .pdf, plus ``qa.jsonl`` with gold labels. The output is
committed (datasets/seeded) so graders never pay a generation step; this
script exists so the corpus is reproducible and extensible.

Gold-label scheme: every QA pair stores ``gold_fact`` — a sentence that
appears verbatim (single line) in exactly one document. At eval time the gold
chunk set is "chunks whose text contains gold_fact", which survives any
chunking configuration (DESIGN.md §13).

Deliberate noise documents exercise the filter stage: an exact duplicate
(dedup), a French document (language), and a boilerplate-only page
(boilerplate). PDFs carry no gold facts — PDF text extraction reflows lines,
so they prove the loader path instead. All content is fictional; PII canaries
are seeded at eval time by the privacy suite (Phase 5), never committed here.

Usage: python scripts/generate_seeded_corpus.py --out datasets/seeded --seed 13
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from fpdf import FPDF


@dataclass(frozen=True)
class QAPair:
    qid: str
    question: str
    answer: str
    gold_doc: str
    gold_fact: str


@dataclass
class Corpus:
    files: dict[str, str] = field(default_factory=dict)  # relpath -> text content
    qa: list[QAPair] = field(default_factory=list)

    def add(self, relpath: str, text: str) -> None:
        assert relpath not in self.files, f"duplicate path {relpath}"
        self.files[relpath] = text

    def ask(self, question: str, answer: str, gold_doc: str, gold_fact: str) -> None:
        assert gold_fact in self.files[gold_doc], f"gold fact not in {gold_doc}: {gold_fact}"
        qid = f"q{len(self.qa) + 1:03d}"
        self.qa.append(QAPair(qid, question, answer, gold_doc, gold_fact))


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    kind: str
    blurb: str


PRODUCTS = (
    Product(
        "AT-300",
        "Helios AT-300",
        "autonomous inspection drone",
        "aerial inspection of industrial sites, flare stacks, and power lines",
    ),
    Product(
        "SR-2",
        "Helios SR-2",
        "survey rover",
        "ground-level mapping and surveying of construction sites and mines",
    ),
    Product(
        "HX-12",
        "Helios HX-12",
        "robotic arm",
        "precision pick-and-place and light assembly on production lines",
    ),
    Product(
        "MV-8",
        "Helios MV-8",
        "warehouse mobile robot",
        "autonomous pallet transport inside fulfillment centers",
    ),
    Product(
        "TD-50",
        "Helios TD-50",
        "tunnel inspection crawler",
        "visual and gas inspection of tunnels, culverts, and pipelines",
    ),
    Product(
        "PL-4",
        "Helios PL-4",
        "palletizing robot",
        "high-throughput case palletizing at end-of-line stations",
    ),
    Product(
        "GS-9",
        "Helios GS-9",
        "gas detection station",
        "fixed-position monitoring of combustible and toxic gases",
    ),
    Product(
        "RB-1",
        "Helios RB-1",
        "dock loading robot",
        "automated trailer loading and unloading at warehouse docks",
    ),
    Product(
        "FL-6",
        "Helios FL-6",
        "forklift retrofit kit",
        "converting manual counterbalance forklifts to autonomous operation",
    ),
    Product(
        "CB-2",
        "Helios CB-2",
        "conveyor inspection bot",
        "rail-mounted monitoring of long conveyor systems",
    ),
)

# Error codes are hand-assigned (not random) so demo queries in the Makefile
# stay stable across regenerations with different seeds.
RUNBOOK_ERRORS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "SR-2": (
        ("E-114", "a LiDAR calibration fault", "re-run the calibration routine on level ground"),
        ("E-117", "a motor encoder desynchronization", "power-cycle the drive unit and re-home"),
    ),
    "AT-300": (
        ("E-201", "a barometer drift warning", "recalibrate the altimeter before takeoff"),
        ("E-204", "a GPS signal degradation event", "hold position and wait for satellite lock"),
    ),
    "MV-8": (
        ("E-310", "a battery thermal warning", "move the unit to a charge bay and let it cool"),
        ("E-312", "a safety scanner obstruction", "clean the scanner window and clear the zone"),
    ),
    "TD-50": (
        ("E-410", "a track tension fault", "adjust the track tensioner to specification"),
        ("E-415", "a gas sensor saturation event", "ventilate the area and zero the sensor"),
    ),
    "GS-9": (
        ("E-520", "a sensor cell end-of-life warning", "replace the electrochemical cell"),
        ("E-523", "a heartbeat link timeout", "check the LTE antenna and signal strength"),
    ),
}


def product_spec_md(corpus: Corpus, product: Product, rng: random.Random) -> None:
    battery_h = rng.randrange(6, 36, 2)
    payload_kg = rng.choice((5, 8, 10, 12, 15, 20, 25, 40, 60, 120))
    speed = round(rng.uniform(0.8, 6.0), 1)
    charge_min = rng.randrange(45, 240, 15)
    weight_kg = rng.randrange(9, 320, 7)
    price_usd = rng.randrange(12_000, 95_000, 1_000)
    firmware = f"{rng.randint(2, 5)}.{rng.randint(0, 9)}.{rng.randint(0, 20)}"

    path = f"products/{product.sku.lower()}-spec.md"
    fact_battery = f"The {product.sku} has a battery life of {battery_h} hours."
    fact_payload = f"The {product.sku} carries a maximum payload of {payload_kg} kg."
    fact_speed = f"The {product.sku} reaches a top speed of {speed} m/s."
    fact_charge = f"A full charge of the {product.sku} takes {charge_min} minutes."
    fact_weight = f"The {product.sku} weighs {weight_kg} kg."
    fact_price = f"The {product.sku} is priced at {price_usd:,} USD."
    fact_firmware = f"The current firmware version for the {product.sku} is {firmware}."

    article = "an" if product.kind[0] in "aeiou" else "a"
    text = f"""# {product.name} specification

The {product.name} is {article} {product.kind} designed for {product.blurb}. It is part of the
Helios Robotics industrial automation line and integrates with the Helios Fleet Manager
for scheduling, telemetry, and over-the-air updates.

## Specifications

{fact_battery} {fact_charge}
{fact_payload} {fact_weight}
{fact_speed} The drive system uses brushless motors with regenerative braking.

## Software

{fact_firmware} Firmware updates are delivered over the air through Fleet Manager and
can be staged to a test group before fleet-wide rollout. The {product.sku} exposes a
local REST interface for diagnostics and supports MQTT for telemetry streaming.

## Pricing and availability

{fact_price} Volume discounts apply to orders of ten or more units. Standard lead time
is six weeks from purchase order.
"""
    corpus.add(path, text)
    corpus.ask(
        f"What is the battery life of the {product.sku} {product.kind}?",
        f"{battery_h} hours",
        path,
        fact_battery,
    )
    corpus.ask(
        f"How much does the {product.sku} cost?",
        f"{price_usd:,} USD",
        path,
        fact_price,
    )
    corpus.ask(
        f"What is the maximum payload of the {product.sku}?",
        f"{payload_kg} kg",
        path,
        fact_payload,
    )


def runbook_md(corpus: Corpus, product: Product) -> None:
    errors = RUNBOOK_ERRORS[product.sku]
    path = f"runbooks/{product.sku.lower()}-troubleshooting.md"
    sections = []
    for code, meaning, resolution in errors:
        fact = f"Error code {code} on the {product.sku} indicates {meaning}."
        sections.append(
            f"## {code}\n\n{fact} To resolve it, {resolution}. If the error persists "
            f"after two attempts, open a support ticket and attach the diagnostic bundle "
            f"exported from Fleet Manager."
        )
    text = (
        f"# {product.name} troubleshooting runbook\n\n"
        f"This runbook covers the most common error codes reported by the {product.sku} "
        f"{product.kind}. Always check the unit's event log in Fleet Manager before "
        f"replacing hardware.\n\n" + "\n\n".join(sections) + "\n"
    )
    corpus.add(path, text)
    for code, meaning, _ in errors:
        fact = f"Error code {code} on the {product.sku} indicates {meaning}."
        corpus.ask(
            f"What does error code {code} mean on the {product.sku}?",
            meaning,
            path,
            fact,
        )


def handbook_docs(corpus: Corpus, rng: random.Random) -> None:
    vacation_days = rng.randrange(18, 30)
    sick_days = rng.randrange(8, 15)
    oncall_days = rng.choice((5, 7, 14))
    key_rotation = rng.choice((30, 60, 90))
    meal_limit = rng.randrange(40, 90, 5)
    remote_days = rng.randint(2, 4)
    parental_weeks = rng.randrange(12, 26, 2)
    refresh_years = rng.randint(3, 4)

    fact_vacation = f"Full-time employees receive {vacation_days} days of paid vacation per year."
    vacation = f"""# Vacation policy

{fact_vacation} Vacation accrues monthly and unused days roll over up to a cap of ten
days. Requests go through the HR portal and need manager approval at least two weeks in
advance for absences longer than three days.

Employees also receive {sick_days} paid sick days per year, which do not roll over.
Public holidays follow the provincial calendar of each employee's home office.
"""
    corpus.add("handbook/vacation.md", vacation)
    corpus.ask(
        "How many days of paid vacation do employees get?",
        f"{vacation_days} days",
        "handbook/vacation.md",
        fact_vacation,
    )

    fact_oncall = f"The on-call rotation lasts {oncall_days} days."
    oncall = f"""On-call guide

{fact_oncall} Rotations hand over on Mondays at 10 a.m. Eastern Time. The on-call
engineer is the first responder for production alerts and is expected to acknowledge
pages within five minutes during business hours and fifteen minutes overnight.

Compensation for on-call weeks follows the engineering compensation addendum. Swaps
are allowed with 48 hours notice in the scheduling tool.
"""
    corpus.add("handbook/oncall.txt", oncall)
    corpus.ask(
        "How long is the on-call rotation?",
        f"{oncall_days} days",
        "handbook/oncall.txt",
        fact_oncall,
    )

    fact_keys = f"API keys must be rotated every {key_rotation} days."
    security = f"""# Security policy

{fact_keys} Rotation is enforced automatically by the secrets manager, which revokes
keys that exceed the rotation window. Hardware security keys are required for access to
production systems, and SSH access goes through the bastion with session recording.

Report suspected phishing to the security team within one hour of receipt. Laptops must
run the managed endpoint agent at all times.
"""
    corpus.add("handbook/security.md", security)
    corpus.ask(
        "How often must API keys be rotated?",
        f"every {key_rotation} days",
        "handbook/security.md",
        fact_keys,
    )

    fact_meals = f"Meal expenses are reimbursed up to {meal_limit} USD per day."
    expenses = f"""Expense policy

{fact_meals} Receipts are required for any expense above 25 USD. Submit reports within
30 days of the expense date through the finance portal; approvals route to your cost
center owner.

Flights must be booked through the corporate travel tool. Economy class applies to
flights under six hours.
"""
    corpus.add("handbook/expenses.txt", expenses)
    corpus.ask(
        "What is the daily meal expense limit?",
        f"{meal_limit} USD",
        "handbook/expenses.txt",
        fact_meals,
    )

    fact_remote = f"Employees may work remotely up to {remote_days} days per week."
    remote = f"""# Remote work policy

{fact_remote} Teams set their own anchor days for in-person collaboration; engineering
anchors on Tuesdays and Thursdays. Fully remote arrangements require VP approval and an
updated employment agreement.

Home office equipment is provided through the IT portal up to the standard allowance.
"""
    corpus.add("handbook/remote-work.md", remote)
    corpus.ask(
        "How many days per week can employees work remotely?",
        f"{remote_days} days",
        "handbook/remote-work.md",
        fact_remote,
    )

    fact_parental = f"Parental leave lasts {parental_weeks} weeks at full pay."
    parental = f"""# Parental leave

{fact_parental} Leave can be taken in up to two blocks within the first year. The
company tops up statutory benefits to full salary for the duration of the leave, and
benefits coverage continues uninterrupted.

Notify HR at least eight weeks before the planned start date to arrange coverage.
"""
    corpus.add("handbook/parental-leave.md", parental)
    corpus.ask(
        "How long is parental leave?",
        f"{parental_weeks} weeks",
        "handbook/parental-leave.md",
        fact_parental,
    )

    fact_refresh = f"Laptops are refreshed every {refresh_years} years."
    equipment = f"""# Equipment policy

{fact_refresh} Earlier replacement requires an approved support ticket documenting the
hardware fault. Standard issue is a 14-inch laptop; engineers may request a 16-inch
model with manager approval.

Peripherals are self-serve through the IT portal up to the annual accessory budget.
"""
    corpus.add("handbook/equipment.md", equipment)
    corpus.ask(
        "How often are laptops refreshed?",
        f"every {refresh_years} years",
        "handbook/equipment.md",
        fact_refresh,
    )

    badge_hours = rng.choice((24, 48, 72))
    fact_badge = f"Lost badges must be reported within {badge_hours} hours."
    facilities = f"""Facilities and badge policy

{fact_badge} Replacement badges are issued at the front desk with photo ID. Tailgating
through secured doors is prohibited; every entry requires an individual badge scan.

Visitors must be registered in advance and escorted at all times in lab areas.
"""
    corpus.add("handbook/facilities.txt", facilities)
    corpus.ask(
        "Within how many hours must a lost badge be reported?",
        f"{badge_hours} hours",
        "handbook/facilities.txt",
        fact_badge,
    )


def kb_articles(corpus: Corpus) -> None:
    articles = (
        (
            "kb/fleet-manager-mqtt.md",
            "Connecting robots to Fleet Manager over MQTT",
            "All Helios robots publish telemetry to Fleet Manager over MQTT with TLS 1.3.",
            "Which protocol do Helios robots use to stream telemetry to Fleet Manager?",
            "MQTT with TLS 1.3",
        ),
        (
            "kb/fleet-manager-sso.md",
            "Single sign-on for Fleet Manager",
            "Fleet Manager supports single sign-on through SAML 2.0 identity providers.",
            "Which standard does Fleet Manager use for single sign-on?",
            "SAML 2.0",
        ),
        (
            "kb/data-retention.md",
            "Telemetry data retention",
            "Telemetry data is retained in Fleet Manager for 13 months by default.",
            "How long is telemetry data retained in Fleet Manager by default?",
            "13 months",
        ),
        (
            "kb/api-rate-limits.md",
            "Fleet Manager API rate limits",
            "The Fleet Manager API allows 600 requests per minute per organization.",
            "What is the Fleet Manager API rate limit?",
            "600 requests per minute per organization",
        ),
    )
    for path, title, fact, question, answer in articles:
        text = f"""# {title}

{fact} This article explains the configuration steps, prerequisites, and the most
common pitfalls our support team sees in the field.

## Setup

Provision credentials in the Fleet Manager admin console, then apply the configuration
to each robot from the fleet settings page. Changes propagate at the next telemetry
heartbeat, normally within one minute.

## Troubleshooting

If the connection does not establish, verify network egress rules and certificate
validity, then consult the event log for the exact handshake error.
"""
        corpus.add(path, text)
        corpus.ask(question, answer, path, fact)


def faq_html(corpus: Corpus, rng: random.Random) -> None:
    warranty_months = rng.choice((12, 18, 24, 36))
    fact_warranty = f"The standard warranty period is {warranty_months} months."
    fact_support = "Support is available from 8 a.m. to 6 p.m. Eastern Time on weekdays."
    text = f"""<!DOCTYPE html>
<html>
<head><title>Helios Robotics — Frequently asked questions</title></head>
<body>
<h1>Frequently asked questions</h1>
<h2>Warranty</h2>
<p>{fact_warranty}</p>
<p>Extended coverage of up to five years can be purchased per unit at order time.</p>
<h2>Support</h2>
<p>{fact_support}</p>
<p>Enterprise plans include a 24/7 emergency line for production-down incidents.</p>
<h2>Spare parts</h2>
<p>Spare parts ship from regional depots and arrive within three business days for
standard orders.</p>
</body>
</html>
"""
    corpus.add("support/faq.html", text)
    corpus.ask(
        "How long is the standard warranty period?",
        f"{warranty_months} months",
        "support/faq.html",
        fact_warranty,
    )
    corpus.ask(
        "What are the support hours?",
        "8 a.m. to 6 p.m. Eastern Time on weekdays",
        "support/faq.html",
        fact_support,
    )


def notes_docs(corpus: Corpus) -> None:
    fact_release = "Firmware 4.2 added dynamic obstacle avoidance for the MV-8."
    release = f"""# Release notes — 2025

## Q4

{fact_release} The update also reduced average pick cycle time by eight percent and
fixed a rare watchdog reset during charger handoff.

## Q3

The AT-300 gained terrain-relative hold for windy conditions. Fleet Manager added
scheduled report exports and a fleet-wide firmware staging view.
"""
    corpus.add("notes/release-notes-2025.md", release)
    corpus.ask(
        "Which firmware version added dynamic obstacle avoidance for the MV-8?",
        "Firmware 4.2",
        "notes/release-notes-2025.md",
        fact_release,
    )

    fact_sales = "The MV-8 led unit sales in the first quarter."
    meeting = f"""Quarterly business review notes, April 2026

{fact_sales} Demand was driven by two large fulfillment network deployments in Ontario.
The services team flagged spare-part lead times as the top customer complaint, and a
regional depot expansion was approved to address it.

Engineering reported that the FL-6 retrofit kit passed its safety certification audit
on the first attempt.
"""
    corpus.add("notes/qbr-2026-04.txt", meeting)
    corpus.ask(
        "Which product led unit sales in the first quarter?",
        "the MV-8",
        "notes/qbr-2026-04.txt",
        fact_sales,
    )


def pdf_docs(out_corpus: Path) -> list[str]:
    """Two small PDFs. No gold facts in PDFs: text extraction reflows lines,
    so they exercise the loader path rather than carry labels."""
    docs = {
        "support/warranty-policy.pdf": (
            "Helios Robotics Warranty Policy",
            "This document describes the warranty terms that apply to Helios Robotics "
            "hardware products. Coverage begins on the date of delivery and applies to "
            "defects in materials and workmanship under normal use. Consumable parts "
            "such as filters, tracks, and battery packs are covered for ninety days. "
            "Warranty service is provided through authorized service centers. Units "
            "modified outside of documented service procedures are excluded from "
            "coverage, as is damage caused by operation outside the published "
            "environmental envelope.",
        ),
        "support/safety-guidelines.pdf": (
            "Helios Robotics Safety Guidelines",
            "Read this guide before operating any Helios Robotics product. Keep a "
            "clear zone around moving robots and never disable a safety scanner while "
            "a unit is energized. Lockout procedures must be followed during "
            "maintenance. Only trained operators may modify fleet traffic rules. "
            "Emergency stop buttons are located on the chassis and in the Fleet "
            "Manager console; test them at the start of every shift. Report any "
            "near-miss incident through the safety portal within one business day.",
        ),
    }
    for relpath, (title, body) in docs.items():
        path = out_corpus / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", "B", 14)
        pdf.multi_cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=11)
        pdf.multi_cell(0, 6, body, new_x="LMARGIN", new_y="NEXT")
        pdf.output(str(path))
    return list(docs)


def noise_docs(corpus: Corpus) -> None:
    # Exact duplicate of the vacation policy: the dedup filter must drop it.
    # ("handbook/..." sorts before "noise/...", so the original is kept.)
    corpus.add("noise/duplicate-vacation.md", corpus.files["handbook/vacation.md"])

    # French document: the language filter must drop it.
    corpus.add(
        "noise/communique-fr.txt",
        """Communiqué interne

Nous sommes heureux d'annoncer l'ouverture de notre nouveau bureau à Montréal.
L'équipe d'ingénierie locale se concentrera sur les systèmes de navigation et la
perception. Les employés intéressés par une mutation peuvent contacter les ressources
humaines avant la fin du trimestre. Une journée portes ouvertes sera organisée le mois
prochain avec des démonstrations de tous nos produits phares.
""",
    )

    # Boilerplate-only page: after line stripping, too little content remains.
    corpus.add(
        "noise/promo.html",
        """<!DOCTYPE html>
<html>
<head><title>Helios Robotics</title></head>
<body>
<p>Home | About Us | Contact | Careers</p>
<p>Subscribe to our newsletter for updates.</p>
<p>We use cookies. See our cookie policy and cookie settings.</p>
<p>Terms of service apply.</p>
<p>Copyright 2026 Helios Robotics.</p>
<p>All rights reserved.</p>
</body>
</html>
""",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("datasets/seeded"))
    parser.add_argument("--seed", type=int, default=13)
    args = parser.parse_args()

    rng = random.Random(args.seed)
    corpus = Corpus()

    for product in PRODUCTS:
        product_spec_md(corpus, product, rng)
    for product in PRODUCTS:
        if product.sku in RUNBOOK_ERRORS:
            runbook_md(corpus, product)
    handbook_docs(corpus, rng)
    kb_articles(corpus)
    faq_html(corpus, rng)
    notes_docs(corpus)
    noise_docs(corpus)

    out_corpus = args.out / "corpus"
    if out_corpus.exists():
        shutil.rmtree(out_corpus)
    for relpath, text in corpus.files.items():
        path = out_corpus / relpath
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    pdf_paths = pdf_docs(out_corpus)

    qa_path = args.out / "qa.jsonl"
    with qa_path.open("w", encoding="utf-8") as fh:
        for pair in corpus.qa:
            fh.write(json.dumps(pair.__dict__, ensure_ascii=False) + "\n")

    total_files = len(corpus.files) + len(pdf_paths)
    print(f"wrote {total_files} corpus files and {len(corpus.qa)} QA pairs to {args.out}")


if __name__ == "__main__":
    main()
