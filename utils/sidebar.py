import streamlit as st


def render_sidebar() -> str:
    """Render consistent sidebar, return current ticker."""
    with st.sidebar:
        st.markdown(
            """<div style="text-align:center;padding:10px 0 6px 0;">
            <span style="color:#00FF41;font-size:18px;font-weight:bold;
                font-family:'Courier New',monospace;letter-spacing:3px;">
                ▶ QUANT TERMINAL
            </span>
            </div>""",
            unsafe_allow_html=True,
        )
        st.markdown("---")

        default = st.session_state.get('ticker', 'AAPL')
        entered = st.text_input(
            "TICKER SYMBOL",
            value=default,
            placeholder="AAPL, RELIANCE.NS …",
            help="US stocks: AAPL | Indian NSE: RELIANCE.NS | BSE: RELIANCE.BO",
        ).upper().strip()

        if entered:
            st.session_state['ticker'] = entered

        st.markdown(
            "<div style='font-size:11px;color:#555;font-family:monospace;margin-top:2px;'>"
            "NSE → append .NS &nbsp;|&nbsp; BSE → append .BO</div>",
            unsafe_allow_html=True,
        )
        st.markdown("---")
        st.markdown(
            "<div style='font-size:11px;color:#444;font-family:monospace;'>PHASE 1 — FUNDAMENTALS</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<div style='font-size:11px;color:#2a6e2a;font-family:monospace;margin-top:6px;'>"
            "PHASE 2 — SEPA ENGINE ✓</div>",
            unsafe_allow_html=True,
        )

    return st.session_state.get('ticker', 'AAPL')
