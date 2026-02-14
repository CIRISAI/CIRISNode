import json

from cirisnode.schema.config_models import CIRISConfigV1, LLMConfigV1
from cirisnode.db.pg_pool import get_pg_pool


async def get_config() -> CIRISConfigV1:
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow("SELECT config_json FROM config WHERE id = 1")
    if row is None:
        default = CIRISConfigV1(llm=LLMConfigV1())
        await save_config(default)
        return default
    data = json.loads(row["config_json"]) if isinstance(row["config_json"], str) else row["config_json"]
    return CIRISConfigV1.model_validate(data)


async def save_config(config: CIRISConfigV1) -> None:
    config_json = config.model_dump_json()
    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO config (id, version, config_json)
            VALUES (1, $1, $2::jsonb)
            ON CONFLICT (id) DO UPDATE SET version = $1, config_json = $2::jsonb
            """,
            config.version, config_json,
        )
