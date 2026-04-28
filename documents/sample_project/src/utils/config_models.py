"""Pydantic models for configuration validation."""
from pydantic import BaseModel, validator, Field
from typing import Dict, List, Optional


class BrowserConfig(BaseModel):
    headless: bool = True
    viewport: Dict[str, int] = Field(default={"width": 1440, "height": 900})
    
    @validator('viewport')
    def validate_viewport(cls, v):
        if v.get('width', 0) < 800 or v.get('height', 0) < 600:
            raise ValueError('Viewport must be at least 800x600')
        return v


class PathsConfig(BaseModel):
    base_url: str = Field(..., pattern=r'^https?://.+')


class BotConfig(BaseModel):
    id: str = Field(default="UNKNOWN", min_length=1)
    name: str = Field(default="Earnest CRM Bot")


class TracingConfig(BaseModel):
    enabled: bool = True
    screenshots: bool = True
    snapshots: bool = True
    sources: bool = True


class BaseConfig(BaseModel):
    paths: PathsConfig
    browser: BrowserConfig = BrowserConfig()
    bot_details: BotConfig = BotConfig()
    tracing: TracingConfig = TracingConfig()


class EmailConfig(BaseModel):
    provider: Optional[str] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    use_tls: bool = True
    
    @validator('smtp_port')
    def validate_port(cls, v):
        if v is not None and (v < 1 or v > 65535):
            raise ValueError('Port must be between 1 and 65535')
        return v