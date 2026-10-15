import argparse
import asyncio
from dataclasses import dataclass
from time import perf_counter

import httpx


def parse_args():
    parser = argparse.ArgumentParser(
        description='Измерение скорости загрузки файла'
    )
    parser.add_argument('url', help='URL файла для загрузки')
    parser.add_argument('--requests', type=int, default=10)
    parser.add_argument('--timeout', type=float, default=10.0)
    args = parser.parse_args()
    if args.requests <= 0:
        parser.error("--requests должен быть больше 0")
    if args.timeout <= 0:
        parser.error("--timeout должен быть больше 0")
    return args

MAX_UNSUCCESSFUL_PART: float = 0.2
RETRYABLE_STATUS_CODES: set[int] = {429, 500, 502, 503, 504}

@dataclass
class RequestResult:
    elapsed: float
    bytes_size: int


@dataclass
class MeasurementResult:
    total_time: float = 0
    total_bytes: int = 0
    successful_requests: int = 0
    requests_amount: int = 10
    unsuccessful_requests: int = 0

    def add_request(self, request: RequestResult) -> None:
        self.total_time += request.elapsed
        self.total_bytes += request.bytes_size
        self.successful_requests += 1

    @property
    def average_time(self) -> float:
        if self.successful_requests == 0:
            return 0.0
        return self.total_time / self.successful_requests

    @property
    def average_speed_bytes_per_second(self) -> float:
        if self.total_time == 0:
            return 0.0
        return self.total_bytes / self.total_time

    def is_measurement_valid(self) -> bool:
        if self.successful_requests == 0:
            return False
        unsuccessful_part = self.unsuccessful_requests / self.requests_amount
        return unsuccessful_part <= MAX_UNSUCCESSFUL_PART


async def measure_request(client: httpx.AsyncClient, url: str) -> RequestResult:
    start = perf_counter()
    response = await client.get(url)
    response.raise_for_status()
    time_result = perf_counter() - start
    bytes_size = len(response.content)
    return RequestResult(time_result, bytes_size)

async def measure_request_with_retry(
        client: httpx.AsyncClient,
        url: str,
        max_attempts: int = 3
) -> RequestResult | None:
    default_delay = 0.5
    max_delay = 5.0
    for attempt in range(1, max_attempts + 1):
        try:
            return await measure_request(client, url)
        except httpx.TimeoutException:
            error_message = "Превышено время ожидания"
        except httpx.NetworkError:
            error_message = "Ошибка сети"
        except httpx.HTTPStatusError as e:
            if e.response.status_code not in RETRYABLE_STATUS_CODES:
                raise
            error_message = f'HTTP code: {e.response.status_code}'

        if attempt == max_attempts:
            print(
                f"Запрос не удался после {max_attempts} попыток. "
                f"Причина: {error_message}"
            )
            return None
        await asyncio.sleep(min(default_delay * 2 ** (attempt - 1), max_delay))



async def main(url: str, requests_amount: int, timeout: float) -> None:
    measurement_result = MeasurementResult(requests_amount=requests_amount)
    async with httpx.AsyncClient(timeout=timeout) as client:
        for _ in range(measurement_result.requests_amount):
            request = await measure_request_with_retry(client, url)
            if request is None:
                measurement_result.unsuccessful_requests += 1
                continue
            measurement_result.add_request(request)
            await asyncio.sleep(0.2)

    if not measurement_result.is_measurement_valid():
        print(
            "Недостаточно успешных запросов для измерения. "
            f"Успешно: {measurement_result.successful_requests}/"
            f"{measurement_result.requests_amount}, "
            f"неудачно: {measurement_result.unsuccessful_requests}."
        )
        return

    print(
        f'Среднее время запроса {measurement_result.average_time:.2f} сек.'
    )
    print(
        f'Объем скачанных данных {(measurement_result.total_bytes / 1_000_000):.2f} МБ'
    )
    print(
        f'Средняя скорость загрузки\n'
        f' {(measurement_result.average_speed_bytes_per_second / 1_000_000):.2f} МБ/сек'
    )

if __name__ == '__main__':
    args = parse_args()
    asyncio.run(main(args.url, args.requests, args.timeout))