"""Shared rendering for new and historical company reports."""
import json
import streamlit as st
from ventureos.logging_utils import logged


@logged
def render_report(report):
    data = report['artifact']['content']
    st.subheader(data['company'])
    if report['mode'] == 'fixture':
        st.warning('Synthetic demo report, not live company intelligence.')
    summary = data.get('company_summary')
    st.subheader('Company summary')
    if summary:
        st.write(summary['text'])
        st.caption('Sources: ' + ', '.join(summary['source_ids']))
    else:
        st.write('A general company overview was not returned. Research highlights follow.')
    for key, label in [('problems','Problems'), ('trends','Trends'), ('buying_signals','Buying signals')]:
        with st.expander(label, expanded=key == 'problems'):
            if not data[key]:
                st.write('No supported findings from the sampled sources.')
            for item in data[key]:
                st.write(item['text'])
                st.caption(item['basis'].capitalize() + ' · Sources: ' + ', '.join(item['source_ids']))
    with st.expander('Evidence quality and conflicts'):
        quality=data.get('quality',{})
        if quality:
            st.write('Missing source categories: ' + ', '.join(quality.get('missing_source_types',[])))
            st.write('Stale sources: ' + ', '.join(quality.get('stale_source_ids',[])))
            st.write('Sources with unknown publication dates: ' + ', '.join(quality.get('undated_source_ids',[])))
        for conflict in data.get('conflicts',[]):
            st.write(conflict['text'])
            st.caption('Sources: ' + ', '.join(conflict['source_ids']))
    with st.expander('Sources and limitations'):
        for source in data['sources']:
            st.write(source['id'] + ': ' + source['url'])
            st.caption('Type: ' + source.get('kind','unknown') + ' | Retrieved: ' + source['retrieved_at'])
            for category in ('problems','trends','buying_signals'):
                for finding in data[category]:
                    for evidence in finding.get('evidence',[]):
                        if evidence['source_id']==source['id']:
                            st.text(evidence['quote'])
        for uncertainty in data['uncertainties']:
            st.write(uncertainty)
        st.caption('Research samples a bounded set of pages. It does not crawl the entire website; PDFs, JavaScript-rendered content, and blocked sources may be unavailable.')
    st.download_button('Download report', json.dumps(report, indent=2), 'company-research.json', 'application/json')
