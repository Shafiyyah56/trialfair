"""Agent 2 dashboard placeholder; start with streamlit run app/ui/dashboard.py."""


def main() -> None:
    """Import Streamlit only on launch so contract work needs no UI dependencies."""
    import streamlit as st

    st.title("TrialFair")
    st.write("Investigate sex-specific clinical trial safety signals and evidence gaps.")
    st.info("Shared scaffold only. Agent implementations and the live pipeline are pending.")


if __name__ == "__main__":
    main()
