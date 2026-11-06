-- CAM 3.4 test-stack schema. Runs once on an empty data volume (postgres image init).
-- Built from docs/Database/logic-database.md (3.3 baseline) and the columns the tool servers
-- read and write. It is a FIXTURE for the compose stack; the production dump is not in the repo.
CREATE DATABASE logic_db_2;
CREATE DATABASE file_metadata_db_2;

\connect logic_db_2
CREATE TABLE quote_routing_profiles (
    profile_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    profile_name varchar NOT NULL UNIQUE,
    routing_sequence jsonb NOT NULL,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE system_skills_registry (
    skill_code varchar PRIMARY KEY,
    skill_index integer NOT NULL UNIQUE,
    skill_name varchar NOT NULL,
    macro_category_name varchar NOT NULL,
    mcp_tool_name varchar NOT NULL,
    input_template jsonb NOT NULL DEFAULT '{}'::jsonb,
    requires_llm boolean DEFAULT false,
    is_active boolean DEFAULT true,
    created_at timestamp DEFAULT CURRENT_TIMESTAMP,
    macro_category integer
);
INSERT INTO quote_routing_profiles (profile_name, routing_sequence) VALUES (
    'Standard_BOM_Flow',
    '["centum_intake__standardize_scrub_bom", "centum_intake__standardize_quote_win", "centum_intake__standardize_costing_sheet", "centum_reporting__cbom", "centum_reporting__enrich_costing_sheet", "centum_reporting__resolve_final_selection", "centum_reporting__generate_reports", "centum_reporting__export_reports"]'
);

\connect file_metadata_db_2
CREATE TABLE rfq_process_tracking (
    rfq_id varchar NOT NULL,
    rfq_process_stage integer NOT NULL DEFAULT 0,
    hitl_required boolean NOT NULL DEFAULT false,
    triggered_by varchar DEFAULT 'SYSTEM_API',
    created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP,
    version integer NOT NULL DEFAULT 1,
    is_active boolean NOT NULL DEFAULT true,
    PRIMARY KEY (rfq_id, version)
);
CREATE UNIQUE INDEX idx_rfq_process_tracking_one_active ON rfq_process_tracking (rfq_id) WHERE is_active;
CREATE TABLE rfq_file_telemetry (
    file_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    rfq_id varchar NOT NULL,
    version integer NOT NULL DEFAULT 1,
    file_role varchar NOT NULL,
    file_path text,
    file_type varchar,
    scan_status varchar,
    execution_logs jsonb,
    processed_at timestamp,
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamp NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_rfq_file_telemetry_rfq_version ON rfq_file_telemetry (rfq_id, version);

-- Currency rates read by the reporting cbom step (currency.get_currency_rates). Fixture: USD only,
-- the default quote currency. Real rates come from the production dump.
\connect logic_db_2
CREATE TABLE currency_conversion_rates (
    currency_code varchar PRIMARY KEY,
    conversion_rate double precision NOT NULL,
    is_active boolean NOT NULL DEFAULT true
);
INSERT INTO currency_conversion_rates VALUES ('USD', 1.0, true);
-- Default quote currency (currency.get_default_quote_currency). Same DDL as the daemon's
-- ensureCurrencySchema() in accomplish-ui/apps/daemon/src/browser-api-server.ts.
CREATE TABLE currency_settings (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    default_quote_currency_code VARCHAR(3) NOT NULL REFERENCES currency_conversion_rates(currency_code),
    updated_at TIMESTAMP DEFAULT now()
);
INSERT INTO currency_settings (id, default_quote_currency_code) VALUES (1, 'USD');
