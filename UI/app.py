"""Local-only company research interface. Start from the repository root."""
from ventureos.logging_utils import logged
import json
import streamlit as st
from UI.service import research, missing_configuration, saved_reports, history_labels
from UI.views import render_report

st.set_page_config(page_title='Venture OS', page_icon='🔎', layout='centered')
st.title('Venture OS')
st.caption('Turn company research into a concise, source-backed business overview.')

@logged
def select_page(name):
    st.session_state.page = name


page = st.session_state.get('page', 'Research')
with st.sidebar:
    st.header('Pages')
    for name, key in [('Research', 'nav_research'), ('Data Management', 'nav_data')]:
        st.button(name, key=key, use_container_width=True,
                  type='primary' if page == name else 'secondary',
                  on_click=select_page, args=(name,))

if page == 'Data Management':
    st.subheader('Data Management')
    st.caption('Latest 100 successful reports from this local UI and CLI. Demo reports are not stored.')
    st.button('Refresh results')
    try:
        reports = saved_reports()
    except ValueError as error:
        st.error(str(error))
        reports = None
    if reports == []:
        st.info('No saved reports yet. Run live research to save a company report.')
    if reports:
        labels = history_labels(reports)
        selected = st.selectbox('Select a saved database report', range(len(reports)),
            index=None, placeholder='Choose a company report', format_func=lambda index: labels[index])
        if selected is not None:
            report = reports[selected]
            st.caption('Saved: ' + report['saved_at'] + ' | Run: ' + report['run_id'])
            render_report(report)

else:
    demo = st.toggle('Demo mode', value=False, help='Shows a synthetic example without keys, database, or network.')
    if demo:
        st.info('Demo uses a fictional company and does not research the inputs below.')
    else:
        missing = missing_configuration()
        if missing:
            st.info('Live research needs local configuration: ' + ', '.join(missing))

    with st.form('company_research'):
        company = st.text_input('Company name', placeholder='e.g. Acme')
        website = st.text_input('Website', placeholder='https://company.com')
        submitted = st.form_submit_button('Research company', type='primary', key='research_submit')

    if submitted:
        st.session_state.pop('report', None)
        if not demo and (not company.strip() or not website.strip()):
            st.error('Enter both the company name and website.')
        else:
            with st.status('Preparing research', expanded=True) as status:
                @logged
                def show_phase(label):
                    status.update(label=label)
                    st.write(label)
                try:
                    st.session_state.report = research(company, website, demo=demo, on_progress=show_phase)
                    status.update(label='Company report ready', state='complete', expanded=False)
                except ValueError as error:
                    status.update(label='Research stopped', state='error')
                    st.error(str(error))
                except Exception:
                    status.update(label='Research stopped', state='error')
                    st.error('Could not complete research. Check local configuration and try again.')


    if 'report' in st.session_state:
        render_report(st.session_state.report)
