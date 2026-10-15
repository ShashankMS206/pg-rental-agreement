import html
import json
import os
import re
import time

import streamlit as st
from google import genai
from google.genai import types

# Backup models are tried in order if the first one is busy or unavailable.
MODELS = ["gemini-2.5-flash"]
DISCLAIMER = "This is awareness guidance, not legal advice."
COLORS = {"High": "#ffb3b3", "Medium": "#ffe0a3", "Low": "#c8f0c8"}
ICONS = {"High": "🔴", "Medium": "🟠", "Low": "🟢"}

# Unicode ranges used by the built-in language check
SCRIPTS = {"Hindi": (0x0900, 0x097F), "Kannada": (0x0C80, 0x0CFF)}

# ---------- Rule-based safety net ----------
RULES = [
    (r"non[- ]?refundable", "Non-refundable payment", "High"),
    (r"forfeit", "Money can be forfeited", "High"),
    (r"without (any )?(prior )?notice", "Action without notice", "High"),
    (r"sole discretion", "Owner has unchecked discretion", "Medium"),
    (r"lock[- ]?in", "Lock-in period", "Medium"),
    (r"(increase|hike|revise).{0,40}(rent|charges|fees)", "Rent/fee hike clause", "Medium"),
    (r"(extra|additional|miscellaneous).{0,20}charges", "Extra / hidden charges", "Medium"),
    (r"(vacate|evict).{0,40}(immediately|forthwith|24 hours|48 hours)", "Sudden eviction", "High"),
    (r"(वापस नहीं|बिना (पूर्व )?सूचना)", "Hindi: refund/notice red flag", "High"),
    (r"(ಹಿಂತಿರುಗಿಸಲಾಗುವುದಿಲ್ಲ|ಸೂಚನೆ ಇಲ್ಲದೆ)", "Kannada: refund/notice red flag", "High"),
]

# ---------- Sample texts ----------
SAMPLES = {
    "1. Risky PG (many red flags)": """1. A security deposit of Rs. 30,000 is non-refundable and will be forfeited on vacating for any reason.
2. The owner may increase the monthly rent at his sole discretion at any time without prior notice.
3. The tenant must vacate the premises within 24 hours if the owner finds any rule violation.
4. Electricity, water and maintenance will be charged extra as decided by the owner.
5. The tenant has a lock-in period of 11 months. No refund of rent if the tenant leaves earlier.
6. Visitors are not allowed after 9 PM.""",
    "2. Fair PG (mostly safe)": """1. A security deposit equal to two months' rent is payable at joining. It will be refunded within 15 days of vacating, after deducting only documented damages with bills.
2. Either party may end the stay by giving 30 days written notice.
3. Rent is fixed for the first 11 months. Any later revision will be at most 5% and informed 30 days in advance in writing.
4. Electricity is charged as per the sub-meter reading at the actual government rate.
5. There is no lock-in period.
6. Visitors are allowed in the common area until 8 PM. The owner will give 24 hours notice before entering a room, except in emergencies.
7. A receipt will be given for every payment.""",
    "3. Hostel rules (mixed)": """1. Hostel gates close at 10 PM. Late entry attracts a fine of Rs. 500 per instance.
2. Mess charges are fixed at Rs. 4,500 per month and must be paid even if the student is on leave.
3. The warden may inspect any room at any time without notice.
4. The security deposit is refundable 60 days after the student vacates, after clearing all dues.
5. A student who wishes to leave must give one month's notice, otherwise one month's fees will be charged.
6. The decision of the warden on all matters is final.
7. Silence must be maintained after 11 PM. Playing loud music is not allowed.""",
    "4. Formal rental agreement": """1. This agreement is for a period of 11 months starting from the date of signing.
2. The tenant shall pay a refundable security deposit of three months' rent. The landlord may make deductions at his discretion before refund.
3. Monthly rent shall increase by 10% every year.
4. The landlord may terminate this agreement by giving 7 days notice. The tenant must give 2 months notice to terminate.
5. A sum of Rs. 5,000 towards painting charges is non-refundable and will be deducted at the time of vacating.
6. Subletting or sharing the premises with outsiders is strictly prohibited.
7. The tenant shall submit identity proof and complete police verification within 15 days of joining.""",
    "5. Hidden-charges PG": """1. A joining fee of Rs. 5,000 is non-refundable.
2. Wi-Fi charges are Rs. 500 per month, subject to revision by the management.
3. Laundry, room cleaning and AC usage will be charged separately as per the owner's rates.
4. Guests staying for meals will be charged extra at rates decided by the owner.
5. Delay in rent payment will attract a penalty of 10% of the monthly rent for each day of delay.
6. The deposit will be returned only after a new tenant is found for the room.
7. The management is not responsible for loss of any belongings or damage inside the room.""",
    "6. Hindi sample (हिंदी)": """1. सिक्योरिटी डिपॉजिट रु. 25,000 वापस नहीं किया जाएगा।
2. मकान मालिक किसी भी समय बिना पूर्व सूचना के किराया बढ़ा सकता है।
3. नियम तोड़ने पर किरायेदार को 24 घंटे के भीतर कमरा खाली करना होगा।
4. बिजली और पानी का खर्च अलग से लिया जाएगा।
5. रात 10 बजे के बाद मेहमानों को आने की अनुमति नहीं है।""",
    "7. Kannada sample (ಕನ್ನಡ)": """1. ಭದ್ರತಾ ಠೇವಣಿ ರೂ. 20,000 ಹಿಂತಿರುಗಿಸಲಾಗುವುದಿಲ್ಲ.
2. ಮಾಲೀಕರು ಯಾವುದೇ ಸೂಚನೆ ಇಲ್ಲದೆ ಬಾಡಿಗೆಯನ್ನು ಹೆಚ್ಚಿಸಬಹುದು.
3. ರಾತ್ರಿ 10 ಗಂಟೆಯ ನಂತರ ಹೊರಗೆ ಹೋಗಲು ಅನುಮತಿ ಇಲ್ಲ.
4. ವಿದ್ಯುತ್ ಮತ್ತು ನೀರಿನ ಶುಲ್ಕವನ್ನು ಪ್ರತ್ಯೇಕವಾಗಿ ವಸೂಲಿ ಮಾಡಲಾಗುವುದು.""",
}
SAMPLE_NAMES = list(SAMPLES.keys())

PAIRS = {
    "Risky PG vs Fair PG": (SAMPLE_NAMES[0], SAMPLE_NAMES[1]),
    "Hidden-charges PG vs Formal agreement": (SAMPLE_NAMES[4], SAMPLE_NAMES[3]),
    "Hostel rules vs Fair PG": (SAMPLE_NAMES[2], SAMPLE_NAMES[1]),
}

SYSTEM_PROMPT = """You are a tenant-awareness assistant for students who rent PGs/hostels in Bengaluru, India.
You read rental/PG/hostel rules or agreements and flag clauses that could hurt the student.
You give awareness guidance only. NEVER claim to give legal advice.

Risk rubric:
- High: student can lose money or housing with little or no recourse (non-refundable deposit, eviction without notice, unlimited fee hikes, forfeiture, no notice period for owner).
- Medium: unfair or vague but negotiable (long lock-in, unclear extra charges, owner discretion, unrealistic restrictions).
- Low: common and mostly fair, but worth knowing (curfew, guest rules, standard house rules).

Rules:
1. "original_text" MUST be copied EXACTLY, character for character, from the input, in the ORIGINAL language of the input. Never translate it.
2. Only include clauses that matter to the student. Skip filler.
3. Explain in very simple language a first-year student can understand.
4. Write "explanation", "why_risky", "summary" and "questions_for_owner" ENTIRELY in the requested language (use that language's own script, not English letters). Keep JSON keys and the risk labels (Low/Medium/High) and category names in English.
5. Reply with ONLY valid JSON, no markdown fences, using this schema:
{
  "clauses": [
    {"original_text": "...", "category": "Deposit|Notice|Fees|Eviction|Rules|Other",
     "risk": "Low|Medium|High", "explanation": "...", "why_risky": "..."}
  ],
  "questions_for_owner": ["..."],
  "overall_risk": "Low|Medium|High",
  "summary": "one or two sentences"
}"""


@st.cache_resource
def _make_client(key: str):
    return genai.Client(api_key=key)


def get_client():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        try:
            key = st.secrets["GEMINI_API_KEY"]
        except Exception:
            key = None
    if not key:
        st.error(
            "AI analysis is not configured. Set GEMINI_API_KEY in your environment, or add "
            'GEMINI_API_KEY = "your-key" to .streamlit/secrets.toml, then restart the app. '
            "For Streamlit Community Cloud, add it in the app's Settings > Secrets."
        )
        st.stop()
    return _make_client(key.strip())


def parse_json(raw: str) -> dict:
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    start, end = raw.find("{"), raw.rfind("}")
    return json.loads(raw[start : end + 1])


def analyze(text: str, language: str) -> dict:
    client = get_client()
    prompt = f"Language for explanations: {language}\n\nAgreement text:\n\"\"\"\n{text}\n\"\"\""
    last_error = None
    for model in MODELS:
        for attempt in range(4):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        response_mime_type="application/json",
                    ),
                )
                data = parse_json(resp.text)
                data.setdefault("clauses", [])
                data.setdefault("questions_for_owner", [])
                data["_model_used"] = model
                return data
            except Exception as e:
                last_error = e
                msg = str(e)
                if "503" in msg or "UNAVAILABLE" in msg or "429" in msg:
                    time.sleep(2 ** attempt)
                    continue
                if isinstance(e, ValueError):  # bad JSON: retry
                    continue
                break  # other errors (e.g. model not found): try next model
    raise ValueError(f"The AI service is busy or unavailable. Please try again in a minute. ({last_error})")


def analyze_pdf(pdf_bytes: bytes, language: str) -> dict:
    """Analyze an uploaded PDF directly, including scanned pages supported by the model."""
    client = get_client()
    prompt = (
        f"Language for explanations: {language}\n\n"
        "Read the attached rental/PG agreement PDF and identify its relevant clauses. "
        "Keep each original_text copied exactly from the document and in its original language."
    )
    last_error = None
    for model in MODELS:
        for attempt in range(4):
            try:
                resp = client.models.generate_content(
                    model=model,
                    contents=[prompt, types.Part.from_bytes(data=pdf_bytes, mime_type="application/pdf")],
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        response_mime_type="application/json",
                    ),
                )
                data = parse_json(resp.text)
                data.setdefault("clauses", [])
                data.setdefault("questions_for_owner", [])
                data["_model_used"] = model
                return data
            except Exception as e:
                last_error = e
                msg = str(e)
                if "503" in msg or "UNAVAILABLE" in msg or "429" in msg:
                    time.sleep(2 ** attempt)
                    continue
                if isinstance(e, ValueError):
                    continue
                break
    raise ValueError(f"The AI service is busy or unavailable. Please try again in a minute. ({last_error})")


def rule_flags(text: str):
    found = []
    for pattern, label, risk in RULES:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            found.append((label, risk, m.group(0)))
    return found


def highlight(text: str, clauses: list) -> str:
    spans = []
    for c in clauses:
        orig = (c.get("original_text") or "").strip()
        if not orig:
            continue
        i = text.lower().find(orig.lower())
        if i >= 0:
            spans.append((i, i + len(orig), c.get("risk", "Low")))
    spans.sort()
    out, pos = [], 0
    for s, e, risk in spans:
        if s < pos:
            continue
        out.append(html.escape(text[pos:s]))
        out.append(
            f'<mark style="background:{COLORS.get(risk, "#eee")};color:#000;'
            f'padding:2px 4px;border-radius:4px">{html.escape(text[s:e])}</mark>'
        )
        pos = e
    out.append(html.escape(text[pos:]))
    return "<div style='white-space:pre-wrap;line-height:1.7'>" + "".join(out) + "</div>"


def count_risks(data: dict) -> dict:
    counts = {"High": 0, "Medium": 0, "Low": 0}
    for c in data["clauses"]:
        r = c.get("risk", "Low")
        counts[r] = counts.get(r, 0) + 1
    return counts


def language_check(data: dict, language: str, text: str):
    """Returns a list of (ok, message) checks for testing Hindi/Kannada output."""
    checks = []
    clauses = data["clauses"]

    # 1. Is the explanation written in the right script?
    if language in SCRIPTS:
        parts = []
        for c in clauses:
            parts += [c.get("explanation", ""), c.get("why_risky", "")]
        parts += data["questions_for_owner"]
        parts.append(data.get("summary", ""))
        letters = [ch for ch in " ".join(parts) if ch.isalpha()]
        if letters:
            lo, hi = SCRIPTS[language]
            ratio = sum(1 for ch in letters if lo <= ord(ch) <= hi) / len(letters)
            checks.append((ratio >= 0.6, f"Explanations are mostly in {language} script ({ratio:.0%} of letters)"))
        else:
            checks.append((False, "No explanation text found to check"))

    # 2. Did the AI keep original_text untranslated, so highlighting works?
    valid = [c for c in clauses if (c.get("original_text") or "").strip()]
    matched = sum(1 for c in valid if c["original_text"].strip().lower() in text.lower())
    checks.append((valid and matched == len(valid), f"{matched} of {len(valid)} clauses matched your text exactly (needed for highlighting)"))

    # 3. Are risk labels valid English labels?
    labels_ok = all(c.get("risk") in ("Low", "Medium", "High") for c in clauses)
    checks.append((labels_ok, "All risk labels are Low / Medium / High"))

    # 4. Did we get questions?
    checks.append((len(data["questions_for_owner"]) >= 3, f"{len(data['questions_for_owner'])} questions for the owner generated (expected 3 or more)"))
    return checks


def render_result(data: dict, text: str, language: str, show_check: bool):
    counts = count_risks(data)
    overall = data.get("overall_risk", "Medium")
    st.subheader(f"{ICONS.get(overall, '')} Overall risk: {overall}")
    if data.get("summary"):
        st.write(data["summary"])
    c1, c2, c3 = st.columns(3)
    c1.metric("High risk", counts["High"])
    c2.metric("Medium risk", counts["Medium"])
    c3.metric("Low risk", counts["Low"])

    st.markdown("#### Your text, with risky parts highlighted")
    st.markdown(highlight(text, data["clauses"]), unsafe_allow_html=True)

    st.markdown("#### Clause-by-clause explanation")
    order = {"High": 0, "Medium": 1, "Low": 2}
    for c in sorted(data["clauses"], key=lambda x: order.get(x.get("risk", "Low"), 3)):
        risk = c.get("risk", "Low")
        with st.expander(f"{ICONS.get(risk, '')} {risk} · {c.get('category', 'Other')} · {c.get('original_text', '')[:70]}..."):
            st.markdown(f"**Clause:** _{c.get('original_text', '')}_")
            st.markdown(f"**What it means:** {c.get('explanation', '')}")
            st.markdown(f"**Why it can be a problem:** {c.get('why_risky', '')}")

    flags = rule_flags(text)
    if flags:
        st.markdown("#### Quick keyword checks")
        for label, risk, matched in flags:
            st.markdown(f"- {ICONS[risk]} **{label}** (found: `{matched}`)")

    st.markdown("#### Questions to ask the owner before signing")
    questions = "\n".join(f"{i}. {q}" for i, q in enumerate(data["questions_for_owner"], 1))
    st.markdown(questions)
    st.download_button("Download questions as text", questions, file_name="questions_for_owner.txt")

    if show_check:
        st.markdown("#### 🧪 Language check (testing tool)")
        st.caption(f"Language selected: {language} · Model used: {data.get('_model_used', 'unknown')}")
        for ok, msg in language_check(data, language, text):
            st.markdown(f"{'✅' if ok else '❌'} {msg}")
        st.info(
            "These checks only test the script and structure. A teammate who speaks the language "
            "should still read the explanations to confirm they sound natural and are correct."
        )


def run_analysis(pdf_file, text: str, language: str) -> dict:
    """Analyze an uploaded PDF if there is one, otherwise the pasted text."""
    if pdf_file is not None:
        return analyze_pdf(pdf_file.getvalue(), language)
    return analyze(text, language)


def has_input(pdf_file, text: str) -> bool:
    return pdf_file is not None or len((text or "").strip()) >= 30


def show_top_concerns(title: str, data: dict):
    st.markdown(f"**{title}**")
    high = [c for c in data["clauses"] if c.get("risk") == "High"]
    if not high:
        st.markdown("- No high-risk clauses found.")
    for c in high:
        st.markdown(f"- {c.get('explanation', '')}")


# ---------------- Callbacks to load samples ----------------
def load_sample(target_key: str, select_key: str):
    st.session_state[target_key] = SAMPLES[st.session_state[select_key]]


def load_pair(pair_key: str):
    a, b = PAIRS[st.session_state[pair_key]]
    st.session_state["textA"] = SAMPLES[a]
    st.session_state["textB"] = SAMPLES[b]


# ---------------- UI ----------------
st.set_page_config(page_title="PG Agreement Red-Flag Spotter", page_icon="🏠", layout="wide")
st.title("🏠 PG & Hostel Agreement Red-Flag Spotter")
st.warning(DISCLAIMER)
st.caption("Text or PDFs you submit are sent to the AI for analysis and are not stored by this app.")

language = st.sidebar.selectbox("Explanation language", ["English", "Hindi", "Kannada"])
show_check = st.sidebar.checkbox("🧪 Show language check (for testing)", value=True)
st.sidebar.info(DISCLAIMER)

tab1, tab2 = st.tabs(["🔍 Analyze one agreement", "⚖️ Compare two PGs"])

with tab1:
    uploaded_pdf = st.file_uploader(
        "Upload your rental agreement (PDF)",
        type=["pdf"],
        help="Upload a PDF to analyze it directly. The PDF is sent to the AI service for analysis.",
        key="agreement_pdf",
    )
    if uploaded_pdf:
        st.caption(f"Selected: {uploaded_pdf.name}")

    sc1, sc2 = st.columns([3, 1])
    sc1.selectbox("Choose a sample text", SAMPLE_NAMES, key="sel1")
    sc2.write("")
    sc2.write("")
    sc2.button("Load sample", on_click=load_sample, args=("text1", "sel1"))

    text1 = st.text_area("Paste your PG / hostel rules or rental agreement here", key="text1", height=260)
    if st.button("Analyze agreement", type="primary"):
        if uploaded_pdf:
            with st.spinner("Reading the agreement PDF..."):
                try:
                    pdf_data = analyze_pdf(uploaded_pdf.getvalue(), language)
                    # PDF text is supplied to the model directly; use its verbatim clauses
                    # as the display text for the existing result renderer.
                    pdf_text = "\n\n".join(
                        c.get("original_text", "") for c in pdf_data["clauses"]
                    )
                    render_result(pdf_data, pdf_text, language, show_check)
                except Exception as e:
                    st.error(f"Something went wrong: {e}")
        elif len(text1.strip()) < 30:
            st.error("Please paste a longer agreement text.")
        else:
            with st.spinner("Reading the fine print..."):
                try:
                    render_result(analyze(text1, language), text1, language, show_check)
                except Exception as e:
                    st.error(f"Something went wrong: {e}")

with tab2:
    p1, p2 = st.columns([3, 1])
    p1.selectbox("Quick comparison presets", list(PAIRS.keys()), key="pairsel")
    p2.write("")
    p2.write("")
    p2.button("Load pair", on_click=load_pair, args=("pairsel",))

    colA, colB = st.columns(2)
    pdfA = colA.file_uploader(
        "Upload PG A agreement (PDF)", type=["pdf"], key="pdfA",
        help="Optional. If you upload a PDF, it is used instead of the text box below.",
    )
    pdfB = colB.file_uploader(
        "Upload PG B agreement (PDF)", type=["pdf"], key="pdfB",
        help="Optional. If you upload a PDF, it is used instead of the text box below.",
    )

    colA.selectbox("Sample for PG A", SAMPLE_NAMES, key="selA", index=0)
    colA.button("Load into PG A", on_click=load_sample, args=("textA", "selA"))
    colB.selectbox("Sample for PG B", SAMPLE_NAMES, key="selB", index=1)
    colB.button("Load into PG B", on_click=load_sample, args=("textB", "selB"))

    textA = colA.text_area("Or paste PG A agreement", height=240, key="textA")
    textB = colB.text_area("Or paste PG B agreement", height=240, key="textB")

    if st.button("Compare", type="primary"):
        if not has_input(pdfA, textA) or not has_input(pdfB, textB):
            st.error("Please upload a PDF or paste text (at least a few lines) for both PG A and PG B.")
        else:
            with st.spinner("Comparing the two agreements..."):
                try:
                    a = run_analysis(pdfA, textA, language)
                    b = run_analysis(pdfB, textB, language)
                    ca, cb = count_risks(a), count_risks(b)
                    st.table(
                        {
                            "": ["Overall risk", "High-risk clauses", "Medium-risk clauses", "Low-risk clauses"],
                            "PG A": [a.get("overall_risk"), ca["High"], ca["Medium"], ca["Low"]],
                            "PG B": [b.get("overall_risk"), cb["High"], cb["Medium"], cb["Low"]],
                        }
                    )
                    score_a, score_b = ca["High"] * 3 + ca["Medium"], cb["High"] * 3 + cb["Medium"]
                    if score_a == score_b:
                        st.info("Both look similar in risk. Compare price, location and food too.")
                    else:
                        st.success(f"PG {'A' if score_a < score_b else 'B'} has fewer risky clauses.")
                    show_top_concerns("Top concerns in PG A", a)
                    show_top_concerns("Top concerns in PG B", b)
                except Exception as e:
                    st.error(f"Something went wrong: {e}")

    st.markdown("#### Checklist to compare PGs in person")
    st.markdown(
        """
- [ ] Deposit amount and how/when it is refunded
- [ ] Notice period (for you AND for the owner)
- [ ] Monthly rent, and how much it can increase per year
- [ ] Electricity, water, Wi-Fi, maintenance: included or extra?
- [ ] Lock-in period and exit penalty
- [ ] Food quality, timings and meal count
- [ ] Curfew and visitor rules
- [ ] Safety: CCTV, security, women's/men's-only rules
- [ ] Distance to college and public transport
- [ ] Written receipt for every payment
"""
    )

st.divider()
st.caption(DISCLAIMER)
