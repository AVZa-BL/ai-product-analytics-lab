{% macro raw_parquet(scenario_name, table_name) %}
    {% set allowed_scenarios = ['live_strategy', 'subscription', 'hybrid_subscription'] %}
    {% if scenario_name not in allowed_scenarios %}
        {{ exceptions.raise_compiler_error('Unsupported scenario: ' ~ scenario_name) }}
    {% endif %}
    read_parquet(
        '{{ var("raw_data_root") }}/{{ scenario_name }}/{{ table_name }}.parquet'
    )
{% endmacro %}
