using System.Globalization;
using System.Text.Json;
using System.Text.RegularExpressions;

using Aijade.Memory.Lexical;
using Aijade.Memory.Model;
using Aijade.Core.Js;

namespace Aijade.Memory.Locomo;

// LoCoMo (Maharana et al., ACL 2024) is not redistributed with this repository; load it from a local copy and
// check its SHA-256 (LocomoCorpus.Sha256).

public sealed record LocomoQuestion(string Question, string Answer, IReadOnlyList<string> Evidence, int Category);

public sealed record LocomoConversation(
    string SampleId, IReadOnlyList<Episode> Episodes, IReadOnlyList<LocomoQuestion> Qa, IReadOnlySet<string> EvidenceIds, double EndTs);

public static class LocomoCorpus
{
    /// <summary>SHA-256 of the locomo10.json file every published number was computed on.</summary>
    public const string Sha256 = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4";

    public const double Day = 86_400_000;

    private static readonly Dictionary<string, int> Months = new()
    {
        ["january"] = 0, ["february"] = 1, ["march"] = 2, ["april"] = 3, ["may"] = 4, ["june"] = 5, ["july"] = 6, ["august"] = 7,
        ["september"] = 8, ["october"] = 9, ["november"] = 10, ["december"] = 11, ["jan"] = 0, ["feb"] = 1, ["mar"] = 2, ["apr"] = 3,
        ["jun"] = 5, ["jul"] = 6, ["aug"] = 7, ["sep"] = 8, ["sept"] = 8, ["oct"] = 9, ["nov"] = 10, ["dec"] = 11,
    };

    private static readonly Regex WithTime = new(
        "([0-9]{1,2}):([0-9]{2})" + JsText.Space + "*(am|pm).*?([0-9]{1,2})" + JsText.Space + "+([a-z]+),?" + JsText.Space + "*([0-9]{4})",
        JsText.Options(ignoreCase: true));

    private static readonly Regex DateOnly = new(
        "([0-9]{1,2})" + JsText.Space + "+([a-z]+),?" + JsText.Space + "*([0-9]{4})", JsText.Options(ignoreCase: true));

    private static readonly Regex SessionKey = new("^session_([0-9]+)$", JsText.Options(false));

    /// <summary>JavaScript Date.UTC: out-of-range day / hour values roll over instead of throwing.</summary>
    public static double DateUtc(int year, int month, int day, int hour = 0, int minute = 0, int second = 0)
    {
        var dt = new DateTime(year, 1, 1, 0, 0, 0, DateTimeKind.Utc)
            .AddMonths(month).AddDays(day - 1).AddHours(hour).AddMinutes(minute).AddSeconds(second);
        return (dt - DateTime.UnixEpoch).TotalMilliseconds;
    }

    /// <summary>Parse timestamps such as "1:56 pm on 8 May, 2023"; null when unparseable.</summary>
    public static double? ParseDate(string s)
    {
        var m = WithTime.Match(s);
        if (m.Success)
        {
            var hh = int.Parse(m.Groups[1].Value, CultureInfo.InvariantCulture);
            var mm = int.Parse(m.Groups[2].Value, CultureInfo.InvariantCulture);
            var ap = JsText.Lower(m.Groups[3].Value);
            var day = int.Parse(m.Groups[4].Value, CultureInfo.InvariantCulture);
            if (!Months.TryGetValue(JsText.Lower(m.Groups[5].Value), out var mon))
                return null;
            var yr = int.Parse(m.Groups[6].Value, CultureInfo.InvariantCulture);
            if (ap == "pm" && hh != 12)
                hh += 12;
            if (ap == "am" && hh == 12)
                hh = 0;
            return DateUtc(yr, mon, day, hh, mm);
        }
        var d = DateOnly.Match(s);
        if (d.Success)
        {
            if (!Months.TryGetValue(JsText.Lower(d.Groups[2].Value), out var mon))
                return null;
            return DateUtc(int.Parse(d.Groups[3].Value, CultureInfo.InvariantCulture), mon, int.Parse(d.Groups[1].Value, CultureInfo.InvariantCulture), 12);
        }
        return null;
    }

    /// <summary>
    /// Map one LoCoMo conversation to episodes. Stated assumption: a turn referenced by some question's gold evidence is
    /// encoded with a "salient" profile; the gate is allowed to act on it, and under NO_GATING it is ignored.
    /// </summary>
    public static LocomoConversation ParseConversation(JsonElement raw)
    {
        var conv = raw.GetProperty("conversation");
        var qa = raw.GetProperty("qa").EnumerateArray().Select(q => new LocomoQuestion(
            q.TryGetProperty("question", out var qq) ? qq.GetString() ?? "" : "",
            q.TryGetProperty("answer", out var aa) ? aa.ValueKind == JsonValueKind.String ? aa.GetString()! : aa.GetRawText() : "",
            q.TryGetProperty("evidence", out var ev) && ev.ValueKind == JsonValueKind.Array
                ? ev.EnumerateArray().Where(x => x.ValueKind == JsonValueKind.String).Select(x => x.GetString()!).ToList()
                : [],
            q.TryGetProperty("category", out var cat) && cat.ValueKind == JsonValueKind.Number ? cat.GetInt32() : 0)).ToList();
        var evidenceIds = qa.SelectMany(q => q.Evidence).ToHashSet();

        var episodes = new List<Episode>();
        double endTs = 0;
        foreach (var prop in conv.EnumerateObject())
        {
            var m = SessionKey.Match(prop.Name);
            if (!m.Success || prop.Value.ValueKind != JsonValueKind.Array)
                continue;
            var sessNo = int.Parse(m.Groups[1].Value, CultureInfo.InvariantCulture);
            var dtStr = conv.TryGetProperty($"{prop.Name}_date_time", out var dt) && dt.ValueKind == JsonValueKind.String ? dt.GetString()! : "";
            var parsed = ParseDate(dtStr);
            var tsBase = parsed ?? (DateUtc(2023, 0, 1) + (sessNo * Day));
            if (parsed is { } p && p > endTs)
                endTs = p;

            var turnIndex = 0;
            foreach (var t in prop.Value.EnumerateArray())
            {
                var diaId = t.GetProperty("dia_id").GetString()!;
                var salient = evidenceIds.Contains(diaId);
                var encoding = salient
                    ? new Encoding(0.9, 0.7, 0.5, new Affect(0.85, 0.6, 0.7))
                    : new Encoding(0.25, 0.15, 0.5, new Affect(0.5, 0.4, 0.5));
                var tags = new List<string>();
                if (t.TryGetProperty("query", out var query) && query.ValueKind == JsonValueKind.String)
                    tags.AddRange(Tokenizer.Tokenize(query.GetString()!));
                if (t.TryGetProperty("blip_caption", out var cap) && cap.ValueKind == JsonValueKind.String)
                    tags.AddRange(Tokenizer.Tokenize(cap.GetString()!).Take(5));
                episodes.Add(new Episode
                {
                    Id = diaId,
                    Content = t.TryGetProperty("text", out var text) && text.ValueKind == JsonValueKind.String ? text.GetString()! : "",
                    CreatedAt = tsBase + (turnIndex * 60_000),
                    LastAccessedAt = tsBase,
                    Encoding = encoding,
                    Context = new EpisodeContext($"session_{sessNo}", t.TryGetProperty("speaker", out var sp) ? sp.GetString() : null, null, tags),
                });
                turnIndex++;
            }
        }
        return new LocomoConversation(raw.GetProperty("sample_id").GetString()!, episodes, qa, evidenceIds, endTs);
    }

    public static IReadOnlyList<LocomoConversation> Load(string path)
    {
        using var doc = JsonDocument.Parse(File.ReadAllBytes(path));
        return doc.RootElement.EnumerateArray().Select(ParseConversation).ToList();
    }

    public static string FileSha256(string path) =>
        Convert.ToHexStringLower(System.Security.Cryptography.SHA256.HashData(File.ReadAllBytes(path)));

    /// <summary>Build a memory instance for one conversation under a given configuration.</summary>
    public static BioticMemory BuildMemory(LocomoConversation conv, MemoryConfig config, Func<Episode, double?>? salienceOf = null,
        bool? selective = null, double? keepFraction = null, IDistiller? distiller = null)
    {
        var memory = new BioticMemory(config, conv.EndTs);
        foreach (var ep in conv.Episodes)
            memory.Encode(new EncodeInput(ep.Id, ep.Content, ep.CreatedAt, ep.Context, ep.BaseStrength, SalienceOverride: salienceOf?.Invoke(ep)));
        memory.Consolidate(distiller ?? new LexicalDistiller(), selective, keepFraction);
        return memory;
    }
}
