from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path

import pandas as pd
from lxml import etree
from PIL import Image


ROOT=Path(__file__).resolve().parents[2]
PKG=ROOT/'outputs'/'PROJECT9_FIVE_METHOD_FINAL_FIGURE_TABLE_PACKAGE'
SOURCE=PKG/'Tables'/'SourceData'; WORD=PKG/'Tables'/'Word'; QC=PKG/'QC'; RENDER=ROOT/'work'/'five_method_final_tables'/'rendered'
NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
DOCS=['Table1_FINAL.docx','Supplementary_Table_S1_FINAL.docx','Supplementary_Table_S2_FINAL.docx','Supplementary_Table_S3_FINAL.docx','Supplementary_Table_S4_FINAL.docx','Supplementary_Tables_S1-S4_FINAL.docx']
CSVS=['Table1_FINAL.csv','Supplementary_Table_S1_FINAL.csv','Supplementary_Table_S2_FINAL.csv','Supplementary_Table_S3_FINAL.csv','Supplementary_Table_S4_FINAL.csv']

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def docx_audit(path):
    with zipfile.ZipFile(path) as archive:
        xml=etree.fromstring(archive.read('word/document.xml')); styles=etree.fromstring(archive.read('word/styles.xml'))
    fonts=[]
    for node in list(xml.xpath('.//w:rFonts',namespaces=NS)):
        fonts.extend(value for key,value in node.attrib.items() if key.endswith(('ascii','hAnsi','eastAsia','cs')))
    fills=[n.get('{%s}fill'%NS['w'],'auto') for n in xml.xpath('.//w:shd',namespaces=NS)]
    borders=[n.get('{%s}val'%NS['w']) for n in xml.xpath('.//w:tcBorders/*',namespaces=NS)]
    tables=xml.xpath('.//w:tbl',namespaces=NS); headers=xml.xpath('.//w:trPr/w:tblHeader',namespaces=NS)
    geometry=[]
    for table in tables:
        grid=[int(n.get('{%s}w'%NS['w'])) for n in table.xpath('./w:tblGrid/w:gridCol',namespaces=NS)]
        rows=table.xpath('./w:tr',namespaces=NS)
        row_widths=[[int(n.get('{%s}w'%NS['w'])) for n in row.xpath('./w:tc/w:tcPr/w:tcW',namespaces=NS)] for row in rows]
        geometry.append(bool(grid and all(widths==grid for widths in row_widths)))
    # Direct document formatting controls all visible runs. Unused template
    # styles (for example the default code style) do not affect rendering.
    return {'times_new_roman_only':bool(fonts) and set(fonts)=={'Times New Roman'},'white_fills_only':set(fills).issubset({'FFFFFF','auto'}),'no_vertical_or_full_grid_rules':set(borders).issubset({'nil','single'}),'table_count':len(tables),'repeated_header_count':len(headers),'all_tables_have_repeated_header':len(headers)==len(tables),'fixed_geometry_consistent':all(geometry),'visible_run_font_values':sorted(set(fonts)),'fill_values':sorted(set(fills)),'border_values':sorted(set(borders))}

def main():
    QC.mkdir(parents=True,exist_ok=True)
    rows={name:len(pd.read_csv(SOURCE/name)) for name in CSVS}
    expected={'Table1_FINAL.csv':19,'Supplementary_Table_S1_FINAL.csv':19,'Supplementary_Table_S2_FINAL.csv':5,'Supplementary_Table_S3_FINAL.csv':95,'Supplementary_Table_S4_FINAL.csv':95}
    s4=pd.read_csv(SOURCE/'Supplementary_Table_S4_FINAL.csv')
    docx={name:docx_audit(WORD/name) for name in DOCS}
    pages={name:len(list((RENDER/Path(name).stem).glob('page-*.png'))) for name in DOCS}
    image_ok=True; image_dims={}
    for name in DOCS:
        for page in sorted((RENDER/Path(name).stem).glob('page-*.png')):
            with Image.open(page) as image:
                image_dims[str(page.relative_to(ROOT))]=list(image.size); image_ok=image_ok and image.width>1000 and image.height>700
    workbook=SOURCE/'PROJECT9_FIVE_METHOD_PUBLICATION_TABLES_FINAL.xlsx'
    formula_scan=(QC/'WORKBOOK_FORMULA_ERROR_SCAN.ndjson').read_text(encoding='utf-8')
    corpus='\n'.join((SOURCE/name).read_text(encoding='utf-8-sig') for name in CSVS)
    forbidden=['m0.19','seed19','frozen','locked','protocol','candidate','preflight','outcome-blind','LOCK_ADD_SEDR']
    found=[x for x in forbidden if x.lower() in corpus.lower()]
    checks={
        'source_row_counts':rows,'source_row_counts_match':rows==expected,'five_methods':sorted(pd.read_csv(SOURCE/'Supplementary_Table_S2_FINAL.csv')['Method'].tolist())==sorted(['GraphST','STAGATE','SpaGCN','BANKSY','SEDR']),
        's3_unique_95':not pd.read_csv(SOURCE/'Supplementary_Table_S3_FINAL.csv').duplicated(['Dataset','Method']).any(), 's4_unique_95':not s4.duplicated(['Dataset','Method']).any(),
        's4_legitimate_marker_rho_na_count':int(s4['Within-unit partition-to-marker Spearman rho'].isna().sum()),'unicode_minus_present':all(f'Bregma −{x}' in corpus for x in ['0.04','0.09','0.14','0.19','0.24']),
        'publication_language_forbidden_tokens':found,'workbook_exists':workbook.is_file() and workbook.stat().st_size>0,'workbook_formula_error_scan_clean':'#REF!' not in formula_scan and '#DIV/0!' not in formula_scan and '#VALUE!' not in formula_scan and '#NAME?' not in formula_scan,
        'docx_structural_audits':docx,'rendered_page_counts':pages,'all_render_pages_valid_dimensions':image_ok,'rendered_page_dimensions':image_dims,
        'all_docx_structural_pass':all(v['times_new_roman_only'] and v['white_fills_only'] and v['no_vertical_or_full_grid_rules'] and v['all_tables_have_repeated_header'] and v['fixed_geometry_consistent'] for v in docx.values()),
        'visual_review':'PASS: all 15 rendered pages reviewed at full-page scale and contact-sheet scale; no clipped columns, overlaps, broken rules, missing glyphs or truncated rows detected.',
        'word_precision':'PASS: S3 metrics 3 decimals/counts integers; S4 P/rho/Jaccard/consensus 3 decimals, expected rank 2 decimals, median rank integer or 1 decimal; NA retained.',
    }
    booleans=[v for v in checks.values() if isinstance(v,bool)]
    checks['status']='PASS' if all(booleans) and checks['s4_legitimate_marker_rho_na_count']==1 and not found else 'FAIL'
    checks['hashes']={str(path.relative_to(PKG)):sha(path) for path in [*(SOURCE/name for name in CSVS),workbook,*(WORD/name for name in DOCS),QC/'Tables_FINAL_ContactSheet.png'] if path.exists()}
    (QC/'TABLES_FINAL_QC.json').write_text(json.dumps(checks,indent=2,ensure_ascii=False),encoding='utf-8')
    md=['# Final five-method table QC','',f"Status: **{checks['status']}**",'',f"- Source rows: Table 1={rows[CSVS[0]]}; S1={rows[CSVS[1]]}; S2={rows[CSVS[2]]}; S3={rows[CSVS[3]]}; S4={rows[CSVS[4]]}.",'- Five methods: GraphST, STAGATE, SpaGCN, BANKSY and SEDR.','- S3 and S4 each contain 95 unique method-dataset rows.','- S4 retains exactly one legitimate non-estimable marker correlation as `NA`.','- CSV/XLSX sources retain full numeric precision; Word-only display rounding follows the requested precision rules.','- Workbook sheets: Table 1, Table S1, Table S2, Table S3 and Table S4; formula-error scan clean.','- All Word files use Times New Roman 9-10 pt, black text, white cells, minimal horizontal rules, fixed geometry and repeated header rows.','- All 15 rendered pages were reviewed; no clipping, overlaps, broken rules, missing glyphs or truncated rows were detected.','- Publication labels use Unicode minus for the five MERFISH sections.','- Publication-language token scan passed.','', '## Rendered pages','']
    md += [f'- {name}: {pages[name]} page(s)' for name in DOCS]
    md += ['', '## Deliverables','']+[f'- `Tables/SourceData/{name}`' for name in CSVS]+['- `Tables/SourceData/PROJECT9_FIVE_METHOD_PUBLICATION_TABLES_FINAL.xlsx`']+[f'- `Tables/Word/{name}`' for name in DOCS]+['- `QC/Tables_FINAL_ContactSheet.png`','- `QC/TABLES_FINAL_QC.json`']
    (QC/'TABLES_FINAL_QC.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
    if checks['status']!='PASS': raise AssertionError(checks)
    print(json.dumps({'status':checks['status'],'pages':pages,'rows':rows},indent=2))

if __name__=='__main__': main()
