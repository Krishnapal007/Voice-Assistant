"""OpenWeatherMap current-weather client for Nova Voice Assistant."""
import json
import os
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class WeatherError(Exception):
    """A friendly, user-displayable weather error."""


def get_current_weather(city):
    city = (city or "").strip()
    if not city:
        raise WeatherError("Please provide a city name, for example: weather in Mumbai.")

    api_key = os.getenv("WEATHER_API_KEY", "").strip()
    if not api_key or api_key.lower() in {"your_openweathermap_api_key", "your_api_key_here"}:
        raise WeatherError(
            "Weather is not configured yet. Add your OpenWeatherMap API key "
            "as WEATHER_API_KEY in the .env file."
        )

    units = os.getenv("WEATHER_UNITS", "metric").strip().lower()
    if units not in {"metric", "imperial", "standard"}:
        units = "metric"

    params = urlencode({"q": city, "appid": api_key, "units": units})
    request = Request(
        "https://api.openweathermap.org/data/2.5/weather?" + params,
        headers={"User-Agent": "NovaVoiceAssistant/1.0"},
    )
    try:
        with urlopen(request, timeout=12) as response:
            data = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        if exc.code == 401:
            raise WeatherError("The OpenWeatherMap API key is invalid or not active yet.") from exc
        if exc.code == 404:
            raise WeatherError(f"I could not find weather information for {city}. Check the city name.") from exc
        if exc.code == 429:
            raise WeatherError("The weather service rate limit was reached. Please try again later.") from exc
        raise WeatherError(f"The weather service returned error {exc.code}.") from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise WeatherError("I could not connect to the weather service. Check your internet connection.") from exc
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise WeatherError("The weather service returned an unexpected response.") from exc

    try:
        description = data["weather"][0]["description"].capitalize()
        temperature = round(float(data["main"]["temp"]))
        feels_like = round(float(data["main"]["feels_like"]))
        humidity = int(data["main"]["humidity"])
        wind_speed = float(data["wind"]["speed"])
        location = data.get("name") or city
        country = data.get("sys", {}).get("country", "")
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise WeatherError("I could not read the weather details for that location.") from exc

    if units == "imperial":
        temp_unit, speed_unit = "°F", "mph"
    elif units == "standard":
        temp_unit, speed_unit = "K", "m/s"
    else:
        temp_unit, speed_unit = "°C", "m/s"

    place = f"{location}, {country}" if country else location
    return (
        f"Current weather in {place}: {description}. "
        f"Temperature {temperature}{temp_unit}, feels like {feels_like}{temp_unit}, "
        f"humidity {humidity} percent, wind speed {wind_speed:g} {speed_unit}."
    )
