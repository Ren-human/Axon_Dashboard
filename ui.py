"""Small reusable presentation helpers; pages remain readable for learners."""
import pandas as pd
import streamlit as st


def table(name):
    return st.session_state['tables'][name].copy()


def require(frame, columns, name):
    missing = sorted(set(columns) - set(frame.columns))
    if frame.empty or missing:
        st.info(f'{name}: no usable rows or missing columns: {", ".join(missing) or "none"}. '
                'Inspect Schema & learning, then update db.py aliases if appropriate.')
        return False
    return True


def raw(frame, name):
    with st.expander('View / download underlying aggregate rows'):
        st.dataframe(frame, hide_index=True)
        st.download_button('Download CSV', frame.to_csv(index=False).encode('utf-8'),
                           f'{name}.csv', 'text/csv', key=f'download_{name}')


def plot(fig, key):
    fig.update_layout(template='plotly_white', margin=dict(l=16, r=16, t=40, b=16),
                      font=dict(size=14), legend=dict(orientation='h', y=-0.2))
    st.plotly_chart(fig, width='stretch', key=key)


def value(number, percent=False):
    if pd.isna(number):
        return 'N/A'
    return f'{number:.1%}' if percent else f'{number:,.0f}'


def lesson(text):
    if st.session_state.get('teaching', True):
        with st.expander('How this page works · 学习提示'):
            st.markdown(text)
