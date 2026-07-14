-- Flatten the raw VARIANT columns landed by src/load_snowflake.py into
-- typed, query-friendly columns. One row per note.

with source as (
    select * from {{ source('raw', 'oncology_extractions') }}
)

select
    note_id,
    run_id,
    method,
    primary_diagnosis,
    primary_site,
    histology,
    tnm_stage:t::string             as t_category,
    tnm_stage:n::string             as n_category,
    tnm_stage:m::string             as m_category,
    tnm_stage:overall_stage::string as overall_stage,
    ecog_performance_status,
    biomarkers,
    medications,
    loaded_at
from source
