with expected as (
    select *
    from (values
        ('pre', true, 'prior_payer'),
        ('pre', true, 'prior_nonpayer'),
        ('pre', false, 'prior_payer'),
        ('pre', false, 'prior_nonpayer'),
        ('post', true, 'prior_payer'),
        ('post', true, 'prior_nonpayer'),
        ('post', false, 'prior_payer'),
        ('post', false, 'prior_nonpayer')
    ) as required(analysis_period, is_subscriber, prior_payer_status)
),
observed as (
    select distinct analysis_period, is_subscriber, prior_payer_status
    from {{ ref('mart_hybrid_subscription__engagement_lift_inputs') }}
)
select expected.*
from expected
left join observed using (analysis_period, is_subscriber, prior_payer_status)
where observed.analysis_period is null
