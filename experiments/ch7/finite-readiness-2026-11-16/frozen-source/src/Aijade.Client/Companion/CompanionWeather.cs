using System.Globalization;
using System.Net.Http.Json;
using System.Text.Json.Nodes;

namespace Aijade.Client.Companion;

public sealed record CompanionPlace(string Name, double Latitude, double Longitude, string TimeZone);

public sealed record WeatherReading(DateTimeOffset At, double Temperature, int Code, string Place)
{
    public string Describe() => $"{Place}，{At:yyyy-MM-dd HH:mm 'UTC'}，{Temperature.ToString("F1", CultureInfo.InvariantCulture)}°C，" +
        (Code switch { 0 => "晴", 1 or 2 => "少云", 3 => "阴", 45 or 48 => "雾", >= 51 and <= 67 => "雨", >= 71 and <= 77 => "雪", >= 80 and <= 82 => "阵雨", 85 or 86 => "阵雪", >= 95 => "雷雨", _ => "天气代码 " + Code }) + "（Open-Meteo）";
}

/// <summary>Open-Meteo geocoding and modelled current conditions, cached for 20 minutes. No location is inferred.</summary>
public sealed class CompanionWeather(HttpClient http, TimeProvider? time = null)
{
    private readonly TimeProvider clock = time ?? TimeProvider.System;
    private readonly System.Collections.Concurrent.ConcurrentDictionary<string, (DateTimeOffset Checked, WeatherReading? Reading)> cache = new(StringComparer.Ordinal);

    public async Task<IReadOnlyList<CompanionPlace>> FindAsync(string city, CancellationToken ct = default)
    {
        if (string.IsNullOrWhiteSpace(city))
            return [];
        var raw = await http.GetFromJsonAsync<JsonObject>("https://geocoding-api.open-meteo.com/v1/search?count=5&language=zh&name=" + Uri.EscapeDataString(city.Trim()), ct).ConfigureAwait(false);
        return (raw?["results"] as JsonArray ?? []).Select(n => new CompanionPlace(
            $"{n!["name"]} {n["admin1"]} {n["country"]}".Trim(), n["latitude"]!.GetValue<double>(), n["longitude"]!.GetValue<double>(), n["timezone"]?.GetValue<string>() ?? "UTC")).ToList();
    }

    public async Task<WeatherReading?> CurrentAsync(CompanionProfile p, CancellationToken ct = default)
    {
        if (!p.Weather || p.Latitude is not { } lat || p.Longitude is not { } lon || !double.IsFinite(lat) || !double.IsFinite(lon) || lat is < -90 or > 90 || lon is < -180 or > 180)
            return null;
        var now = clock.GetUtcNow();
        var key = FormattableString.Invariant($"{lat}:{lon}");
        if (cache.TryGetValue(key, out var cached) && now - cached.Checked < TimeSpan.FromMinutes(cached.Reading is null ? 2 : 20))
            return cached.Reading;
        using var timeout = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeout.CancelAfter(TimeSpan.FromSeconds(6));
        try
        {
            var url = FormattableString.Invariant($"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,weather_code&timeformat=unixtime&timezone=GMT");
            var raw = await http.GetFromJsonAsync<JsonObject>(url, timeout.Token).ConfigureAwait(false);
            var c = raw?["current"];
            var reading = c is null ? null : new WeatherReading(DateTimeOffset.FromUnixTimeSeconds(c["time"]!.GetValue<long>()), c["temperature_2m"]!.GetValue<double>(), c["weather_code"]!.GetValue<int>(), p.City);
            if (reading is not null && (now - reading.At).Duration() > TimeSpan.FromHours(2))
                reading = null;
            cache[key] = (now, reading);
            return reading;
        }
        catch (Exception e) when (!ct.IsCancellationRequested && e is HttpRequestException or OperationCanceledException or System.Text.Json.JsonException or InvalidOperationException or FormatException)
        {
            cache[key] = (now, null);
            return null;
        }
    }
}
