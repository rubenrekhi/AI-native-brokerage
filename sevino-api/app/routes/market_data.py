"""FastAPI router for /v1/market-data/*. Proxies FMP + Alpaca data through a Redis cache."""

from fastapi import APIRouter, Depends, Query, Request

from app.auth import get_current_user
from app.rate_limit import limiter
from app.schemas.market_data import (
    BatchQuoteResponse,
    ChartResponse,
    ChartTimeframe,
    MarketStatusResponse,
    StockInfoResponse,
)
from app.services.market_data import MarketDataService, get_market_data_service

router = APIRouter()

_MAX_BATCH_SYMBOLS = 20


# /stocks/batch MUST be registered before /stocks/{symbol} so FastAPI
# doesn't match "batch" as a ticker symbol path parameter.


@router.get("/stocks/batch", response_model=BatchQuoteResponse)
@limiter.limit("60/minute")
async def get_batch_quotes(
    # `request` is required by the slowapi @limiter.limit decorator.
    request: Request,
    symbols: str = Query(
        ..., description=f"Comma-separated ticker symbols (max {_MAX_BATCH_SYMBOLS})"
    ),
    user_id: str = Depends(get_current_user),
    market_data: MarketDataService = Depends(get_market_data_service),
) -> BatchQuoteResponse:
    symbol_list = [s.strip().upper() for s in symbols.split(",") if s.strip()][
        :_MAX_BATCH_SYMBOLS
    ]
    data = await market_data.get_batch_quotes(symbol_list)
    return BatchQuoteResponse.model_validate(data)


@router.get("/stocks/{symbol}", response_model=StockInfoResponse)
async def get_stock_info(
    symbol: str,
    user_id: str = Depends(get_current_user),
    market_data: MarketDataService = Depends(get_market_data_service),
) -> StockInfoResponse:
    data = await market_data.get_stock_info(symbol)
    return StockInfoResponse.model_validate(data)


@router.get("/stocks/{symbol}/chart", response_model=ChartResponse)
async def get_chart(
    symbol: str,
    timeframe: ChartTimeframe = Query(ChartTimeframe.ONE_MONTH),
    user_id: str = Depends(get_current_user),
    market_data: MarketDataService = Depends(get_market_data_service),
) -> ChartResponse:
    data = await market_data.get_chart(symbol, timeframe.value)
    return ChartResponse.model_validate(data)


@router.get("/market/status", response_model=MarketStatusResponse)
async def get_market_status(
    user_id: str = Depends(get_current_user),
    market_data: MarketDataService = Depends(get_market_data_service),
) -> MarketStatusResponse:
    data = await market_data.get_market_status()
    return MarketStatusResponse.model_validate(data)
