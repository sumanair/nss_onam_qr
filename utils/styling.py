# utils/styling.py
def inject_global_styles():
    import streamlit as st
    st.markdown("""
        <style>
        .card-button {
            background-color: #421503;
            color: #702100;
            border-radius: 10px;
            padding: 0.25rem;
            margin: 0.25rem 0;
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.07);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        .card-button:hover {
            transform: scale(1.01);
            background-color: #A11C1C;
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
        }
        
        /* === Sidebar Styling === */
        section[data-testid="stSidebar"] {
            background-color: #FCFCE8 !important;
            border-right: 2px solid #F4D06F;
            box-shadow: 2px 0 6px rgba(0, 0, 0, 0.04);
        }

        /* === Logo Alignment + Padding Cleanup === */
        .css-6qob1r {
            padding-top: 1rem !important;
        }

        /* === Main Panel Typography === */
        h1, h2, h3 {
            color: #D72638;
            font-weight: 700;
            margin-bottom: 1rem;
        }


        /* === Table Header Styling === */
        .stDataFrame thead  {
            background-color: #800000 !important;  /* Deep maroon */
            color: #F4D06F !important;             /* Soft gold text */
            font-weight: bold;
            font-size: 0.95rem;
            border-bottom: 2px solid #D72638;      /* Accent from your logo */
            padding: 0.75rem 0.5rem;
            text-align: left;
        }
        

        # --- Home Page Content ---    
        .big-title {
            font-size: 2.5rem;
            font-weight: 800;
            margin-bottom: 0.25rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }

        .big-title span.emoji {
            font-size: 2rem;
            line-height: 1;
        }

        .subtitle {
            font-size: 1.2rem;
            margin-bottom: 2rem;
            color: #666;
        }
        .info-box {
            background-color: #f0f2f6;
            padding: 1rem;
            border-radius: 0.5rem;
            border-left: 6px solid #3b82f6;
        }

        </style>
    """, unsafe_allow_html=True)
