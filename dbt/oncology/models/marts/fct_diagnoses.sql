-- Analytics-ready fact: one row per note with diagnosis, site, stage, and the
-- standardized ICD-O-3 topography code (joined from the registry crosswalk seed).
-- Code standardization lives in the transformation layer, where it belongs.

with stg as (
    select * from {{ ref('stg_extractions') }}
),

icdo3 as (
    select * from {{ ref('icdo3_topography') }}
)

select
    stg.note_id,
    stg.run_id,
    stg.primary_site,
    icdo3.icdo3_code,
    icdo3.icdo3_label,
    stg.primary_diagnosis,
    stg.histology,
    stg.overall_stage,
    stg.t_category,
    stg.n_category,
    stg.m_category,
    stg.ecog_performance_status,
    case
        when stg.overall_stage in ('I', 'IIA', 'IIB') then 'early'
        when stg.overall_stage in ('IIIA', 'IIIB')    then 'locally_advanced'
        when stg.overall_stage = 'IV'                 then 'metastatic'
        else 'unknown'
    end as stage_group,
    stg.method,
    stg.loaded_at
from stg
left join icdo3 on stg.primary_site = icdo3.primary_site
