
import streamlit as st

def inject_global_styles():
    st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap');

    html, body, .stApp, [data-testid="stAppViewContainer"] {
      font-family: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial,
                   "Apple Color Emoji","Segoe UI Emoji","Segoe UI Symbol" !important;
      -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale;
      font-size: 16px; line-height: 1.55;
    }

    /* Scale all text in the main container a touch larger */
    .block-container { max-width: 1280px; padding-top: 2rem; margin-top: .75rem; font-size: 1.02rem; }

    /* Headings */
    h1, h2, h3, h4 { color:#1f2937; font-weight: 800; letter-spacing:-0.015em; margin: .2rem 0 .6rem; }
    h1 { font-size: 2.1rem; }
    h2 { font-size: 1.6rem; }
    h3 { font-size: 1.25rem; }
    .big-title { font-size: 2.6rem; font-weight: 900; margin-bottom:.25rem; display:flex; align-items:center; gap:.5rem; }
    .big-title span.emoji { font-size:2rem; line-height:1; }
    .subtitle { font-size:1.05rem; color:#6b7280; margin-bottom:1.2rem; }

    /* Body copy & lists */
    p, li, label, span, div, code, kbd, small { color:#111827; }
    small { color:#6b7280; }

    /* Tables / dataframes */
    .stTable, .stDataFrame { font-size: 0.95rem; }
    .stTable th, .stTable td { padding: .5rem .6rem !important; }

    /* Inputs & buttons */
    .stTextInput > div > div input,
    .stTextArea textarea,
    .stSelectbox div[data-baseweb="select"] div,
    .stNumberInput input {
      font-size: 1rem !important;
    }
    .stButton > button {
      font-weight: 700 !important;
      font-size: 1rem !important;
      border-radius: 12px !important;
    }

    /* Links */
    a { color:#0ea5e9; text-decoration: none; }
    a:hover { text-decoration: underline; }

    /* Your existing colors/layout */
    section[data-testid="stSidebar"] {
      background-color: #FCFCE8 !important;
      border-right: 2px solid #F4D06F;
      box-shadow: 2px 0 6px rgba(0,0,0,0.04);
    }
    .stApp { background-color: #FFFFE5; }
    .stPageLink a::after { content: none !important; }

    /* Feature cards keep your style; just inherit fonts */
    .feature-grid { display:grid; gap:1rem; grid-template-columns:repeat(3,minmax(0,1fr)); }
    @media (max-width:1100px){ .feature-grid { grid-template-columns:1fr 1fr; } }
    @media (max-width:700px){  .feature-grid { grid-template-columns:1fr; } }

    .feature-card {
      background:#FFFCF7; border:1px solid #F1E5D1; border-radius:16px; padding:1rem 1.1rem;
      box-shadow:0 6px 18px rgba(128,0,0,0.06); transition:transform .18s, box-shadow .18s, border-color .18s;
      position:relative; overflow:hidden;
    }
    .feature-card::before { content:""; position:absolute; inset:0 0 auto 0; height:4px;
      background:linear-gradient(90deg,#800000,#D72638,#F4D06F); opacity:.9; }
    .feature-card:hover { transform:translateY(-3px); box-shadow:0 10px 22px rgba(128,0,0,0.12); border-color:#E3D2B3; }
    .fc-head { display:flex; align-items:center; gap:.6rem; margin:.25rem 0 .6rem; }
    .fc-title a { color:#5A0000; font-weight:700; text-decoration:none; }
    .fc-title a:hover { text-decoration:underline; color:#800000; }
    .fc-body { margin-left:0; }
    .fc-desc { font-size:.95rem; line-height:1.45; color:#5A0000; margin:.4rem 0 0; }
    .fc-link { display:inline-block; margin-right:.75rem; color:#5A0000; text-decoration:none; font-weight:600; }
    .fc-link:hover { text-decoration:underline; color:#800000; }
    </style>
    """, unsafe_allow_html=True)

def inject_sidebar_styles():
    import streamlit as st
    st.markdown("""
    <style>
    :root {
      --cream:  #FFFEE0;
      --gold:   #FFD900;
      --orange: #F4A300;  /* keep your current orange; adjust if needed */
      --maroon: #800000;
      --maroon-dark: #7A0000;
    }

    /* ===== Sidebar base ===== */
    section[data-testid="stSidebar"] {
      position: relative !important;
      background-color: var(--cream) !important;
      color: #000 !important;
      padding-top: 20px !important;      /* space away from top kasavu */
      padding-bottom: 24px !important;   /* space above bottom kasavu */
      box-shadow: inset 0 0 0 2px rgba(0,0,0,0.04);
    }
    section[data-testid="stSidebar"] * {
      color: #000 !important;
      font-size: 1.05rem !important;
    }

    /* ===== Kasavu sari bands (top & bottom) ===== */
    section[data-testid="stSidebar"]::before,
    section[data-testid="stSidebar"]::after {
      content: "";
      position: absolute;
      left: 0; right: 0;
      height: 18px;
      z-index: 2;
    }
    /* Top: gold → orange → maroon */
    section[data-testid="stSidebar"]::before {
      top: 0;
      background: linear-gradient(
        to bottom,
        var(--gold)   0%,
        var(--gold)   33%,
        var(--orange) 33%,
        var(--orange) 66%,
        var(--maroon) 66%,
        var(--maroon) 100%
      );
      box-shadow: 0 1px 0 rgba(0,0,0,0.08);
    }
    /* Bottom: maroon → orange → gold */
    section[data-testid="stSidebar"]::after {
      bottom: 0;
      background: linear-gradient(
        to top,
        var(--gold)   0%,
        var(--gold)   33%,
        var(--orange) 33%,
        var(--orange) 66%,
        var(--maroon) 66%,
        var(--maroon) 100%
      );
      box-shadow: 0 -1px 0 rgba(0,0,0,0.08);
    }

    /* Divider line */
    section[data-testid="stSidebar"] hr {
      border-color: rgba(0,0,0,0.12) !important;
    }

    /* ===== Nav links ===== */
    section[data-testid="stSidebar"] nav [data-testid="stSidebarNav"] a,
    section[data-testid="stSidebar"] nav a {
      color: #000 !important;
      border-radius: 12px !important;
      padding: 10px 14px !important;
      font-size: 1.05rem !important;   /* inactive smaller */
      font-weight: 600 !important;     /* inactive bold */
    }
    /* Active pill: larger + heavier */
    section[data-testid="stSidebar"] nav a[aria-current="page"],
    section[data-testid="stSidebar"] nav li a[aria-current="page"] {
      background: var(--maroon) !important;
      color: #ffffff !important;
      font-weight: 700 !important;
      font-size: 1.15rem !important;
      border-radius: 14px !important;
    }

    /* ===== Buttons (e.g., Logout) ===== */
    section[data-testid="stSidebar"] .stButton > button,
    section[data-testid="stSidebar"] button[kind="secondary"] {
      width: 100% !important;            /* full width */
      min-height: 48px !important;       /* bigger touch target */
      background: var(--maroon-dark) !important;
      color: #ffffff !important;
      border: 0 !important;
      border-radius: 18px !important;
      padding: 12px 18px !important;
      font-size: 1.12rem !important;     /* larger label */
      font-weight: 700 !important;
      letter-spacing: 0.2px !important;
      box-shadow: 0 3px 0 rgba(0,0,0,0.18) !important;
      text-align: center !important;
    }
    /* Force any nested spans/markdown/emojis inside the button to white */
    section[data-testid="stSidebar"] .stButton > button *,
    section[data-testid="stSidebar"] .stButton > button p,
    section[data-testid="stSidebar"] .stButton > button svg,
    section[data-testid="stSidebar"] .stButton > button [data-testid="stMarkdownContainer"] * {
      color: #ffffff !important;
      fill: #ffffff !important;
    }

    section[data-testid="stSidebar"] .stButton > button:hover {
      filter: brightness(1.08) !important;
      transform: translateY(-1px);
      transition: all .12s ease-in-out;
    }
    section[data-testid="stSidebar"] .stButton > button:active {
      transform: translateY(0);
      box-shadow: 0 2px 0 rgba(0,0,0,0.2) !important;
    }
    </style>
    """, unsafe_allow_html=True)