-- Explode the biomarkers array so each (note, biomarker) is its own row.
-- Enables queries like "count of HER2-positive breast cases".

with stg as (
    select note_id, primary_site, biomarkers
    from {{ ref('stg_extractions') }}
)

select
    stg.note_id,
    stg.primary_site,
    b.value:name::string   as biomarker_name,
    b.value:status::string as biomarker_status
from stg,
     lateral flatten(input => stg.biomarkers) b
