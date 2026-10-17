"""Evaluate the agent on questions about the three Q3 incidents.

    python agent/eval.py                 # run all questions, LLM judge on
    python agent/eval.py --only q04 q10  # subset
    python agent/eval.py --no-judge      # deterministic checks only

Metrics
- answer correctness: an LLM judge (claude-sonnet-5-5) grades the answer against a reference
  answer and rubric -> pass/fail. Deterministic key-fact regex checks are reported alongside.
- retrieval hit rate: share of questions with an expected document where at least one
  expected document appears in the top 5 of any search_knowledge call the agent made. Also
  reported retriever-only: the raw question used as the query, no agent in the loop.
- citation presence: share of knowledge questions whose answer contains at least one
  well-formed citation; citation validity: every cited source was actually retrieved.

Ground-truth numbers were computed with the CLAUDE.md metric definitions on
data/marketing.duckdb; facts come from knowledge/.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent import config  # noqa: E402
from agent.core import DiceAgent, _api_key, _text  # noqa: E402

KB = "knowledge/"
CITATION = re.compile(r"\[(?:Slack #[\w-]+ \d{4}-\d{2}-\d{2}|Confluence: [^\]]+)\]")

QUESTIONS = [
    # ---------------------------------------------------------------- pure SQL
    {
        "id": "q01", "type": "sql", "topic": "unity",
        "question": "Compare CPI and CTR for the unity_video_retarget campaign between "
                    "2026-07-01..2026-07-08 and 2026-07-09..2026-07-31.",
        "reference": "Jul 1-8: CPI ≈ $1.16, CTR ≈ 1.60%. Jul 9-31: CPI ≈ $0.53, CTR ≈ 7.50%. "
                     "Installs rose from 17,752 to 117,985 while spend stayed ~flat per day.",
        "must": [r"1\.1[56]", r"0\.5[23]", r"1\.60?\s?%", r"7\.50?\s?%"],
        "expected_docs": [],
    },
    {
        "id": "q02", "type": "sql", "topic": "google",
        "question": "How many installs did Google record on Android each day from 2026-08-05 to "
                    "2026-08-10, and what was the CPI each day?",
        "reference": "Aug 5: 4,316 ($1.29); Aug 6: 282 ($21.38); Aug 7: 244 ($24.41); "
                     "Aug 8: 298 ($21.84); Aug 9: 294 ($21.35); Aug 10: 4,490 ($1.33).",
        "must": [r"4,?316", r"\b282\b", r"\b244\b", r"\b298\b", r"\b294\b", r"4,?490", r"21\.3[58]",
                 r"24\.4[01]"],
        "expected_docs": [],
    },
    {
        "id": "q03", "type": "sql", "topic": "android",
        "question": "What was D1 retention on Android and on iOS (all channels incl. Organic) for "
                    "install cohorts 2026-07-08..2026-07-21 versus 2026-07-22..2026-08-04?",
        "reference": "Android 34.4% -> 28.0% (≈ -6.4 pts); iOS 37.9% -> 37.4% (flat).",
        "must": [r"34\.[34]", r"2[78]\.[90]|28\.0", r"37\.9", r"37\.4"],
        "expected_docs": [],
    },
    # ---------------------------------------------------------- pure knowledge
    {
        "id": "q04", "type": "kb", "topic": "unity",
        "question": "What did marketing leadership decide about scaling unity_video_retarget in "
                    "July 2026, and why didn't they pause it?",
        "reference": "No budget increase (budget held flat); fraud ticket with Unity plus a stricter "
                     "Attributa Protect click-flooding rule; exclude it from CPI benchmarks/install "
                     "KPIs; ask for makegoods. Not paused because revenue was unchanged - the real "
                     "users were still there and D7 ROAS was flat; pause only if Unity can't clean "
                     "it up. Approved by the CMO (Marisol Okafor) on 2026-07-17.",
        "must": [r"(?i)no (budget )?increase|flat|not scal|hold", r"(?i)makegood|ticket|Protect",
                 r"(?i)revenue|real users|ROAS"],
        "expected_docs": [KB + "slack/marketing-leads/2026-07-17_unity-scaling-decision.json"],
    },
    {
        "id": "q05", "type": "kb", "topic": "google",
        "question": "What was the root cause of the Google Android attribution outage, and can the "
                    "affected days be restated in our tables?",
        "reference": "A quarterly rotation of network API credentials on the evening of 2026-08-05: "
                     "the Android Google Ads link in Attributa kept a cached token that expired and "
                     "the MMP silently fell back to Organic. iOS re-authenticated fine. The data "
                     "cannot be restated - failed postbacks can't be re-attributed, so Aug 6-9 stays "
                     "misattributed (Organic Android inflated) permanently.",
        "must": [r"(?i)credential|token", r"(?i)can(no|')t be restated|cannot|not be restated|no[t]? .*restat|permanent"],
        "expected_docs": [KB + "confluence/postmortem-2026-08-google-android-attribution.md",
                          KB + "slack/ua-team/2026-08-07_google-android-installs-collapse.json",
                          KB + "slack/ua-team/2026-08-10_google-android-recovered.json"],
    },
    {
        "id": "q06", "type": "kb", "topic": "unity",
        "question": "What was approved for September 2026 regarding unity_video_retarget and "
                    "Android bids?",
        "reference": "Approved 2026-08-28 by Marisol: pause unity_video_retarget from Sep 1 (fraud "
                     "ongoing, partial July credit from Unity) and move its ~$2.7k/day to "
                     "unity_playable_installs; keep Android bids unchanged until 2.15.0 ships. "
                     "(Also: release the 3% holdback into AppLovin.)",
        "must": [r"(?i)paus", r"unity_playable_installs", r"(?i)android bids?.{0,40}(unchanged|no change|not)|2\.15"],
        "expected_docs": [KB + "slack/marketing-leads/2026-08-28_september-budget-reallocation.json",
                          KB + "slack/ua-team/2026-08-25_unity-makegood-update.json"],
    },
    # ------------------------------------------------------------ why (both)
    {
        "id": "q07", "type": "both", "topic": "android",
        "question": "Why did Android D1 retention drop in late July 2026? Was it ad-network "
                    "traffic quality, as was suggested at first?",
        "reference": "No. The drop starts with the 2026-07-22 install cohort, is the same size in "
                     "every channel including Organic, and iOS is flat, so it isn't traffic quality. "
                     "It is the Android 2.14.0 release (100% rollout ~19:00 UTC Jul 21): new asset "
                     "loader (+~9s first load on low/mid devices) and a tutorial step where ~8% "
                     "stall. Data: Android D1 ≈ 34% -> 28%, iOS ≈ flat. Fix in 2.15.0 (target "
                     "early Sep). Decision: no bid cuts.",
        "must": [r"2\.14", r"(?i)organic", r"(?i)not .{0,30}traffic|isn't .{0,20}traffic|app|release"],
        "expected_docs": [KB + "slack/data-questions/2026-07-29_android-retention-by-channel.json",
                          KB + "slack/marketing-leads/2026-07-31_android-retention-escalation.json",
                          KB + "slack/ua-team/2026-07-28_android-d1-drop-traffic-quality.json",
                          KB + "confluence/android-release-log.md"],
    },
    {
        "id": "q08", "type": "both", "topic": "unity",
        "question": "Why did unity_video_retarget's CPI fall so sharply in July 2026, and should "
                    "we trust its installs?",
        "reference": "Invalid traffic (click spam / install fraud) from 2026-07-09, not better "
                     "placements: CTR ~1.6% -> ~7.5-8%, CPI ~$1.16 -> ~$0.53 on flat spend, D1 "
                     "retention ~34% -> ~16%, payer conversion roughly halved. Don't trust the "
                     "installs: exclude from CPI benchmarks; revenue/ROAS look normal because fake "
                     "installs add no revenue and no spend.",
        "must": [r"(?i)fraud|spam|invalid", r"(?i)D1|retention", r"(?i)CTR"],
        "expected_docs": [KB + "slack/data-questions/2026-07-16_unity-video-retarget-analysis.json",
                          KB + "slack/ua-team/2026-07-14_unity-video-retarget-cpi-drop.json",
                          KB + "slack/marketing-leads/2026-07-17_unity-scaling-decision.json",
                          KB + "slack/ua-team/2026-07-17_unity-fraud-ticket.json",
                          KB + "confluence/invalid-traffic-policy.md"],
    },
    {
        "id": "q09", "type": "both", "topic": "google",
        "question": "Why did Organic Android installs roughly double between 2026-08-06 and "
                    "2026-08-09?",
        "reference": "Google Android installs were misattributed to Organic during the Attributa "
                     "outage (credential rotation Aug 5; Android Google link didn't re-auth). Data: "
                     "Organic Android 35,188 over the 4 days (~8.2-9.3k/day vs ~4.1k normal); Google "
                     "Android only 1,118 installs on ~$24.8k spend; total Android installs flat. "
                     "Not real organic growth; can't be restated.",
        "must": [r"(?i)misattribut|attribut", r"(?i)google", r"35,?188|35(\.\d)?k|8,?[12]\d\d|8\.[12]\s?k|9\.[23]\s?k|9,?[23]\d\d|1,?118"],
        "expected_docs": [KB + "confluence/postmortem-2026-08-google-android-attribution.md",
                          KB + "slack/ua-team/2026-08-07_google-android-installs-collapse.json",
                          KB + "slack/ua-team/2026-08-10_google-android-recovered.json",
                          KB + "slack/data-questions/2026-08-07_organic-android-spike.json"],
    },
    # -------------------------------------------- deprecated page must NOT be used
    {
        "id": "q10", "type": "both", "topic": "deprecated",
        "question": "Using the D7 ROAS definition from our wiki, what was paid D7 ROAS for install "
                    "cohorts from 2026-08-17 to 2026-08-23?",
        "reference": "≈ 20.3% using Metric Definitions (v3)/CLAUDE.md: only D7-mature cohorts "
                     "(installs 2026-08-17..08-22; 08-23 is not mature as of 2026-08-29) and their "
                     "spend. The deprecated legacy v1 page (SUM(revenue_d7)/SUM(spend) over all "
                     "rows) would give ≈ 17.1% and must not be used.",
        "must": [r"20\.[23]\d?\s?%|0\.20[23]", r"(?i)matur|08-22|Aug(ust)? 22"],
        "must_not": [r"(?i)(D7 ROAS|answer)\s*(was|is|=|:)\s*\**\s*17\.1"],
        "expected_docs": [KB + "confluence/metric-definitions.md",
                          KB + "slack/data-questions/2026-06-08_how-to-compute-d7-roas.json"],
        "forbidden_docs": [KB + "confluence/d7-roas-definition-legacy.md"],
    },
    # ---------------------------------------------------------------- refusal
    {
        "id": "q11", "type": "refuse", "topic": "google",
        "question": "What was the D30 ROAS for Google Android install cohorts from 2026-08-06 to "
                    "2026-08-09?",
        "reference": "Cannot be answered: as of 2026-08-29 those cohorts are not D30-mature "
                     "(D30 requires install_date ≤ 2026-07-30), revenue_d30 is NULL. The agent must "
                     "not estimate a number. (It may add that these days are also misattributed.)",
        "must": [r"(?i)not (yet )?(be )?(mature|available|possible)|immature|NULL|can(no|')t|cannot|unavailable"],
        "must_not": [r"(?i)D30 ROAS\s*(was|is|=|:|of)\s*\**\s*\d"],
        "expected_docs": [],
    },
]

JUDGE_PROMPT = """You grade answers from an analytics assistant. Compare the ANSWER with the
REFERENCE for the QUESTION.

PASS if the answer's main conclusion and key facts/numbers agree with the reference (numbers may
differ by rounding, about ±0.2 percentage points or ±2%) and it contains no materially false
claim. Extra correct detail is fine. For a question the reference says cannot be answered, PASS
only if the answer declines to give a number and explains why. If the reference says a
deprecated method must not be used, FAIL an answer that reports the deprecated method's number
as the answer.

QUESTION: {question}

REFERENCE: {reference}

ANSWER:
{answer}

Reply with a single JSON object on one line: {{"verdict": "pass" or "fail", "reason": "<one sentence>"}}"""


def judge(llm, q: dict, answer: str) -> dict:
    msg = llm.invoke(JUDGE_PROMPT.format(question=q["question"], reference=q["reference"], answer=answer))
    text = _text(msg.content)
    m = re.search(r"\{.*\}", text, re.S)
    try:
        out = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        out = {}
    return {"verdict": out.get("verdict", "fail"), "reason": out.get("reason", text[:200])}


def grade(q: dict, r) -> dict:
    ans = r.answer
    facts = [bool(re.search(p, ans)) for p in q.get("must", [])]
    leaks = [p for p in q.get("must_not", []) if re.search(p, ans)]
    retrieved = r.retrieved_paths
    retrieved_citations = {h["citation"] for s in r.sources for h in s["hits"]}
    cited = CITATION.findall(ans)
    g = {
        "facts_ok": all(facts) and not leaks,
        "facts_hit": f"{sum(facts)}/{len(facts)}",
        "must_not_hits": leaks,
        "retrieval_hit": (any(d in retrieved for d in q["expected_docs"])
                          if q["expected_docs"] else None),
        "citation_present": bool(cited) if q["type"] in ("kb", "both") else None,
        "citations_valid": (all(c in retrieved_citations for c in cited) if cited else None),
        "invalid_citations": [c for c in cited if c not in retrieved_citations],
        "forbidden_doc_cited": None,
    }
    if q.get("forbidden_docs"):
        # Retrieving the deprecated page is OK only if the answer doesn't rely on it.
        forbidden_cits = {h["citation"] for s in r.sources for h in s["hits"] if h["path"] in q["forbidden_docs"]}
        g["forbidden_doc_cited"] = any(c in ans for c in forbidden_cits) and "deprecat" not in ans.lower()
    return g


def pct(xs: list) -> str:
    xs = [x for x in xs if x is not None]
    return f"{sum(xs)}/{len(xs)} = {100 * sum(xs) / len(xs):.0f}%" if xs else "n/a"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "eval_results.json"))
    args = ap.parse_args()

    qs = [q for q in QUESTIONS if not args.only or q["id"] in args.only]
    agent = DiceAgent()
    llm = None
    if not args.no_judge:
        from langchain_anthropic import ChatAnthropic
        llm = ChatAnthropic(model=config.MODEL, api_key=_api_key(), max_tokens=1024,
                            output_config={"effort": "low"})

    # Retriever-only hit rate: the raw question as the query, no agent in the loop.
    from agent.rag.retriever import get_retriever
    raw_hits = {}
    for q in qs:
        if q["expected_docs"]:
            paths = [h.meta["path"] for h in get_retriever().search(q["question"])]
            raw_hits[q["id"]] = any(d in paths for d in q["expected_docs"])

    rows = []
    for q in qs:
        t0 = time.time()
        r = agent.ask(q["question"])
        g = grade(q, r)
        if llm:
            g["judge"] = judge(llm, q, r.answer)
        g["correct"] = (g["judge"]["verdict"] == "pass") if llm else g["facts_ok"]
        if g["forbidden_doc_cited"]:
            g["correct"] = False
        rows.append({
            "id": q["id"], "type": q["type"], "topic": q["topic"], "question": q["question"],
            "answer": r.answer, "sql": r.sql, "retrieved": r.retrieved_paths,
            "tool_calls": r.tool_calls, "cost_usd": round(r.cost_usd, 4),
            "seconds": round(time.time() - t0, 1), **g,
        })
        mark = "PASS" if g["correct"] else "FAIL"
        print(f"{q['id']} [{q['type']:<6}] {mark}  facts {g['facts_hit']:<5} "
              f"retrieval={g['retrieval_hit']!s:<5} cite={g['citation_present']!s:<5} "
              f"tools={r.tool_calls} ${r.cost_usd:.3f}  {q['question'][:60]}", flush=True)
        if llm and not g["correct"]:
            print(f"      judge: {g['judge']['reason']}")

    print("\n" + "=" * 72)
    print(f"Answer correctness (LLM judge):  {pct([r['correct'] for r in rows])}" if llm else
          f"Answer correctness (key facts):  {pct([r['correct'] for r in rows])}")
    print(f"Key-fact regex checks:           {pct([r['facts_ok'] for r in rows])}")
    print(f"Retrieval hit rate (top 5):      {pct([r['retrieval_hit'] for r in rows])}")
    print(f"Retrieval hit rate (raw query):  {pct(list(raw_hits.values()))}")
    print(f"Citation presence (kb + why):    {pct([r['citation_present'] for r in rows])}")
    print(f"Citation validity:               {pct([r['citations_valid'] for r in rows])}")
    for t in ("sql", "kb", "both", "refuse"):
        sub = [r["correct"] for r in rows if r["type"] == t]
        if sub:
            print(f"  correctness [{t:<6}]          {pct(sub)}")
    dep = [r for r in rows if r["topic"] == "deprecated"]
    for r in dep:
        print(f"Deprecated D7 ROAS page relied on: {r['forbidden_doc_cited']} ({r['id']})")
    print(f"Tool calls: avg {sum(r['tool_calls'] for r in rows) / len(rows):.1f}, "
          f"max {max(r['tool_calls'] for r in rows)} (cap {config.MAX_TOOL_CALLS})")
    print(f"Agent cost: ${sum(r['cost_usd'] for r in rows):.3f} total, "
          f"${sum(r['cost_usd'] for r in rows) / len(rows):.3f}/question")
    Path(args.out).write_text(json.dumps(rows, indent=2, ensure_ascii=False))
    print(f"Details: {args.out}")


if __name__ == "__main__":
    main()
