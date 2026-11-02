"""Plotly figures from checked columns; no eval or generated plotting code."""
import pandas as pd
import plotly.graph_objects as go


def build(result):
    frame = pd.DataFrame(result['rows'], columns=result['columns'])
    spec = result['spec']
    chart = spec.get('output', {}).get('chart_type', 'bar')
    if chart == 'table' or frame.empty:
        return None
    x, ys, series = result['x'], result['y'], result.get('series')
    if x not in frame or not ys or any(y not in frame for y in ys):
        return None
    fig = go.Figure()
    if chart == 'funnel':
        fig.add_trace(go.Funnel(y=frame[x], x=frame[ys[0]], textinfo='value'))
    elif series and series in frame and len(ys) == 1:
        for label, group in frame.groupby(series, sort=False):
            if chart == 'line':
                fig.add_trace(go.Scatter(x=group[x], y=group[ys[0]], name=str(label),mode='lines+markers'))
            else:
                fig.add_trace(go.Bar(x=group[x], y=group[ys[0]], name=str(label)))
    else:
        for y in ys:
            if chart == 'line':
                fig.add_trace(go.Scatter(x=frame[x], y=frame[y], name=y, mode='lines+markers'))
            else:
                fig.add_trace(go.Bar(x=frame[x], y=frame[y], name=y))
    fig.update_layout(template='plotly_white', title=dict(text=''), barmode='group',
                      xaxis_title=x, yaxis_title=result['unit'], height=360,
                      margin=dict(l=15, r=15, t=25, b=40))
    if result['unit'].startswith('fraction'):
        fig.update_yaxes(tickformat='.0%', rangemode='tozero')
    return fig
