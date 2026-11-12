"""Metadata-bound saved-pivot snapshot lookup, not pivot recalculation.

Only single-row-axis grand totals with data fields on columns are certified.
Visible/filter state is represented by saved pivot display cells. Source data
changes do not refresh the pivot; they mark its snapshot dirty for reporting.
"""
from openpyxl.utils.cell import range_boundaries


def extract_pivot_snapshots(worksheet):
    result=[]
    for p in getattr(worksheet,'_pivots',[]):
        c1,r1,c2,r2=range_boundaries(p.location.ref)
        cache=p.cache
        source=cache.cacheSource.worksheetSource if cache and cache.cacheSource else None
        record={'name':p.name,'sheet':worksheet.title,'bounds':(r1,c1,r2,c2),
                'source_table':getattr(source,'name',None),'source_sheet':getattr(source,'sheet',None),
                'source_ref':getattr(source,'ref',None),'source_dirty':False,
                'fields':{},'unsupported_reason':None,'semantics':'saved visible pivot display snapshot; no refresh'}
        reason=None
        if not cache or not cache.cacheSource or cache.cacheSource.type!='worksheet':reason='non-worksheet-cache'
        elif p.location.firstDataRow is None or p.location.firstDataCol is None:reason='missing-layout-offsets'
        elif p.dataOnRows:reason='data-on-rows'
        elif cache and (cache.calculatedItems or cache.calculatedMembers):reason='calculated pivot items/members'
        elif len(p.rowFields or [])!=1:reason='row-axis-layout'
        elif any(x.x!=-2 for x in (p.colFields or [])):reason='column-grouping'
        elif len(p.dataFields)>1 and not p.colItems:reason='multi-field-column-layout'
        grand=[i for i,x in enumerate(p.rowItems or []) if x.t=='grand']
        if len(grand)!=1:reason=reason or 'missing/ambiguous grand row'
        if not reason:
            row=r1+p.location.firstDataRow+grand[0]
            for i,d in enumerate(p.dataFields):
                positions=[j for j,x in enumerate(p.colItems or []) if x.i==i and x.t=='data']
                if len(p.dataFields)==1 and not p.colItems:positions=[0]
                if len(positions)!=1:
                    reason='ambiguous data column';break
                col=c1+p.location.firstDataCol+positions[0]
                if not(r1<=row<=r2 and c1<=col<=c2):reason='target outside pivot';break
                root=cache.cacheFields[d.fld].name if cache and d.fld<len(cache.cacheFields) else None
                for label in (d.name,root):
                    if label:
                        key=label.casefold()
                        if key in record['fields'] and record['fields'][key]!=(row,col):
                            reason='ambiguous data caption';break
                        record['fields'][key]=(row,col)
        record['unsupported_reason']=reason
        result.append(record)
    return result
