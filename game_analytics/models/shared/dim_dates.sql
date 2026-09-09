with date_spine as (
    select cast(range as date) as date_day
    from range(date '2025-01-01', date '2028-01-01', interval 1 day)
)

select
    date_day,
    extract(year from date_day)::integer as year_number,
    extract(month from date_day)::integer as month_number,
    date_trunc('week', date_day)::date as week_start_date,
    extract(isodow from date_day)::integer as day_of_week_number
from date_spine
