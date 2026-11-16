using System.Text.Json.Nodes;
using System.Text.RegularExpressions;

using Aijade.Core.Js;

namespace Aijade.Learning.Forge;

// Skills as SKILL.md packages
// (frontmatter + structured body), their schema, and the markdown form.

public enum SkillPlatform
{
    Macos,
    Linux,
    Windows,
}

public sealed record SkillFrontmatter(string Name, string Description, string Version, string Author, IReadOnlyList<SkillPlatform>? Platforms = null, JsonObject? Metadata = null);

public sealed record SkillBody(
    string Title, IReadOnlyList<string> WhenToUse, IReadOnlyList<string> Procedure, string? Intro = null, IReadOnlyList<string>? Prerequisites = null,
    string? HowToRun = null, IReadOnlyList<string>? QuickReference = null, IReadOnlyList<string>? Pitfalls = null, string? Verification = null);

public enum SkillSource
{
    HandAuthored,
    LlmGenerated,
    Evolved,
}

public sealed record SkillEvolutionEntry(double At, string Feedback, string Summary, string FromVersion, string ToVersion);

/// <summary>An executable part of a skill: the tools it may call and an optional runner.</summary>
public sealed record SkillModule(IReadOnlyList<string>? Tools = null, Func<SkillRunContext, Task<SkillRunResult>>? Run = null);

public sealed record SkillRunContext(string Input, Func<string, JsonNode?, Task<JsonNode?>> CallTool);

public sealed record SkillRunResult(bool Ok, string Output);

public sealed record SkillPackage(SkillFrontmatter Frontmatter, SkillBody Body, double CreatedAt, double UpdatedAt, SkillSource Source, IReadOnlyList<SkillEvolutionEntry> EvolutionLog, SkillModule? Module = null);

public sealed record SkillDraft(string ProposedName, string Title, string Summary, IReadOnlyList<string> WhenToUse);

public sealed record SkillValidationResult(bool Ok, IReadOnlyList<string> Errors, IReadOnlyList<string> Warnings, double Score);

public static class Skills
{
    /// <summary>A hand-authored skill: version 0.1.0 and author AIJADE unless given, timestamps stamped now.</summary>
    public static SkillPackage Define(string name, string description, SkillBody body, string version = "0.1.0", string author = "AIJADE",
        IReadOnlyList<SkillPlatform>? platforms = null, JsonObject? metadata = null, SkillModule? module = null, double? now = null)
    {
        var at = now ?? DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
        return new SkillPackage(new SkillFrontmatter(name, description, version, author, platforms, metadata), body, at, at, SkillSource.HandAuthored, [], module);
    }
}

/// <summary>Thrown when model output does not satisfy a schema; carries the issue list.</summary>
public sealed class SkillSchemaException(IReadOnlyList<string> issues) : Exception(string.Join("; ", issues))
{
    public IReadOnlyList<string> Issues { get; } = issues;
}

/// <summary>
/// The skill schema, checked on JSON, with fixed issue texts and order (path, then
/// message): length checks and refinements both report, a wrong type stops further checks of that field.
/// </summary>
public static class SkillSchema
{
    private static readonly Regex NamePattern = new("^[a-z0-9]+(?:-[a-z0-9]+)*$", JsText.Options(false));
    private static readonly Regex SemVer = new(@"^\d+\.\d+\.\d+$", JsText.Options(false));

    private static string Received(JsonNode? n, bool exists = false) => n switch
    {
        null => exists ? "null" : "undefined",
        JsonArray => "array",
        JsonObject => "object",
        JsonValue v => v.GetValueKind() switch
        {
            System.Text.Json.JsonValueKind.String => "string",
            System.Text.Json.JsonValueKind.Number => "number",
            System.Text.Json.JsonValueKind.True or System.Text.Json.JsonValueKind.False => "boolean",
            _ => "null",
        },
        _ => "unknown",
    };

    private static bool IsString(JsonNode? n, out string s)
    {
        s = "";
        return n is JsonValue v && v.GetValueKind() == System.Text.Json.JsonValueKind.String && (s = v.GetValue<string>()) is not null;
    }

    private sealed class Issues(List<string> list)
    {
        public void Add(string path, string message) => list.Add($"{(path.Length == 0 ? "skill" : path)}: {message}");

        public bool Type(JsonNode? n, string path, string expected, bool exists = false)
        {
            var ok = expected switch
            {
                "string" => n is JsonValue v && v.GetValueKind() == System.Text.Json.JsonValueKind.String,
                "array" => n is JsonArray,
                "object" or "record" => n is JsonObject,
                _ => false,
            };
            if (!ok)
                Add(path, $"Invalid input: expected {expected}, received {Received(n, exists)}");
            return ok;
        }

        public void Str(JsonObject? o, string path, string key, bool optional, int? min = null, int? max = null, Action<string>? more = null)
        {
            var exists = o is not null && o.TryGetPropertyValue(key, out _);
            var n = o?[key];
            if (optional && !exists)
                return;
            if (!Type(n, $"{path}.{key}", "string", exists))
                return;
            var s = n!.GetValue<string>();
            if (min is { } lo && s.Length < lo)
                Add($"{path}.{key}", $"Too small: expected string to have >={lo} characters");
            if (max is { } hi && s.Length > hi)
                Add($"{path}.{key}", $"Too big: expected string to have <={hi} characters");
            more?.Invoke(s);
        }

        public void StrArray(JsonObject? o, string path, string key, bool optional, int? minItems = null)
        {
            var exists = o is not null && o.TryGetPropertyValue(key, out _);
            var n = o?[key];
            if (optional && !exists)
                return;
            if (!Type(n, $"{path}.{key}", "array", exists))
                return;
            var arr = (JsonArray)n!;
            for (var i = 0; i < arr.Count; i++)
                Type(arr[i], $"{path}.{key}.{i}", "string", true);
            if (minItems is { } m && arr.Count < m)
                Add($"{path}.{key}", $"Too small: expected array to have >={m} items");
        }
    }

    /// <summary>All issues of {frontmatter, body}, in schema order.</summary>
    public static IReadOnlyList<string> Validate(JsonNode? skill)
    {
        var list = new List<string>();
        var issues = new Issues(list);
        if (!issues.Type(skill, "", "object"))
            return list;
        var root = (JsonObject)skill!;
        if (issues.Type(root["frontmatter"], "frontmatter", "object", root.ContainsKey("frontmatter")))
        {
            var fm = (JsonObject)root["frontmatter"]!;
            issues.Str(fm, "frontmatter", "name", false, max: 64, more: s =>
            {
                if (!NamePattern.IsMatch(s))
                    issues.Add("frontmatter.name", "name must be lowercase-hyphenated, no spaces");
            });
            issues.Str(fm, "frontmatter", "description", false, max: 60, more: s =>
            {
                if (!JsText.Trim(s).EndsWith('.'))
                    issues.Add("frontmatter.description", "description must be ONE sentence ending with a period (<=60 chars)");
            });
            issues.Str(fm, "frontmatter", "version", false, more: s =>
            {
                if (!SemVer.IsMatch(s))
                    issues.Add("frontmatter.version", "version must be semver (e.g. 0.1.0)");
            });
            issues.Str(fm, "frontmatter", "author", false, min: 1);
            if (fm.TryGetPropertyValue("platforms", out var platforms) && issues.Type(platforms, "frontmatter.platforms", "array", true))
            {
                var arr = (JsonArray)platforms!;
                for (var i = 0; i < arr.Count; i++)
                {
                    if (!IsString(arr[i], out var p) || p is not ("macos" or "linux" or "windows"))
                        issues.Add($"frontmatter.platforms.{i}", "Invalid option: expected one of \"macos\"|\"linux\"|\"windows\"");
                }
            }
            if (fm.TryGetPropertyValue("metadata", out var metadata))
                issues.Type(metadata, "frontmatter.metadata", "record", true);
        }
        if (issues.Type(root["body"], "body", "object", root.ContainsKey("body")))
        {
            var b = (JsonObject)root["body"]!;
            issues.Str(b, "body", "title", false, min: 1);
            issues.Str(b, "body", "intro", true);
            issues.StrArray(b, "body", "whenToUse", false, 1);
            issues.StrArray(b, "body", "prerequisites", true);
            issues.Str(b, "body", "howToRun", true);
            issues.StrArray(b, "body", "quickReference", true);
            issues.StrArray(b, "body", "procedure", false, 1);
            issues.StrArray(b, "body", "pitfalls", true);
            issues.Str(b, "body", "verification", true);
        }
        return list;
    }

    private static List<string>? Strings(JsonNode? n) => n is JsonArray a ? a.Select(x => x!.GetValue<string>()).ToList() : null;

    private static string? OptStr(JsonNode? n) => n?.GetValue<string>();

    /// <summary>Validate and convert; throws <see cref="SkillSchemaException"/> with the issue list when invalid.</summary>
    public static (SkillFrontmatter Frontmatter, SkillBody Body) Parse(JsonNode? skill)
    {
        var issues = Validate(skill);
        if (issues.Count > 0)
            throw new SkillSchemaException(issues);
        var fm = skill!["frontmatter"]!.AsObject();
        var b = skill["body"]!.AsObject();
        return (new SkillFrontmatter(fm["name"]!.GetValue<string>(), fm["description"]!.GetValue<string>(), fm["version"]!.GetValue<string>(), fm["author"]!.GetValue<string>(),
                Strings(fm["platforms"])?.Select(WireName.Parse<SkillPlatform>).ToList(), fm["metadata"]?.DeepClone().AsObject()),
            new SkillBody(b["title"]!.GetValue<string>(), Strings(b["whenToUse"])!, Strings(b["procedure"])!, OptStr(b["intro"]), Strings(b["prerequisites"]),
                OptStr(b["howToRun"]), Strings(b["quickReference"]), Strings(b["pitfalls"]), OptStr(b["verification"])));
    }

    private static JsonArray Arr(IEnumerable<string> s) => new(s.Select(x => (JsonNode?)x).ToArray());

    /// <summary>The JSON form (field names and order as recorded).</summary>
    public static JsonObject ToJson(SkillFrontmatter fm, SkillBody b)
    {
        var f = new JsonObject { ["name"] = fm.Name, ["description"] = fm.Description, ["version"] = fm.Version, ["author"] = fm.Author };
        if (fm.Platforms is { } p)
            f["platforms"] = Arr(p.Select(WireName.Of));
        if (fm.Metadata is { } m)
            f["metadata"] = m.DeepClone();
        var body = new JsonObject { ["title"] = b.Title };
        if (b.Intro is not null)
            body["intro"] = b.Intro;
        body["whenToUse"] = Arr(b.WhenToUse);
        if (b.Prerequisites is { } pre)
            body["prerequisites"] = Arr(pre);
        if (b.HowToRun is not null)
            body["howToRun"] = b.HowToRun;
        if (b.QuickReference is { } qr)
            body["quickReference"] = Arr(qr);
        body["procedure"] = Arr(b.Procedure);
        if (b.Pitfalls is { } pit)
            body["pitfalls"] = Arr(pit);
        if (b.Verification is not null)
            body["verification"] = b.Verification;
        return new JsonObject { ["frontmatter"] = f, ["body"] = body };
    }
}

/// <summary>SKILL.md: a YAML-ish frontmatter block, the title and intro, then ## sections.</summary>
public static class SkillMarkdown
{
    private static string Section(string heading, IReadOnlyList<string>? items) =>
        items is null || items.Count == 0 ? "" : string.Join("\n", items.Select(i => $"- {i}").Prepend($"## {heading}"));

    private static string Section(string heading, string? text) => text is null ? "" : $"## {heading}\n{text}";

    public static string ToMarkdown(SkillPackage pkg)
    {
        var fm = pkg.Frontmatter;
        var b = pkg.Body;
        var head = new List<string> { "---", $"name: {fm.Name}", $"description: {JsFormat.JsonString(fm.Description)}", $"version: {fm.Version}", $"author: {fm.Author}" };
        if (fm.Platforms is { Count: > 0 } p)
            head.Add($"platforms: [{string.Join(", ", p.Select(x => JsFormat.JsonString(WireName.Of(x))))}]");
        if (fm.Metadata?["tags"] is JsonArray { Count: > 0 } tags)
        {
            head.Add("metadata:");
            head.Add($"  tags: [{string.Join(", ", tags.Select(t => JsFormat.JsonString(t!.GetValue<string>())))}]");
        }
        head.Add("---");
        var blocks = new List<string> { string.Join("\n", head), $"# {b.Title}" };
        if (!string.IsNullOrEmpty(b.Intro))
            blocks.Add(b.Intro);
        blocks.Add(Section("When to Use", b.WhenToUse));
        blocks.Add(Section("Prerequisites", b.Prerequisites));
        blocks.Add(Section("How to Run", b.HowToRun));
        blocks.Add(Section("Quick Reference", b.QuickReference));
        blocks.Add(b.Procedure.Count == 0 ? "" : $"## Procedure\n{string.Join("\n", b.Procedure.Select((s, i) => $"{i + 1}. {s}"))}");
        blocks.Add(Section("Pitfalls", b.Pitfalls));
        blocks.Add(Section("Verification", b.Verification));
        return string.Join("\n\n", blocks.Where(x => x.Length > 0)) + "\n";
    }

    private static readonly Regex Document = new(@"^---\n([\s\S]*?)\n---\n?([\s\S]*)$", JsText.Options(false));
    private static readonly Regex FrontLine = new("^(" + JsText.Space + @"*)([A-Za-z0-9_]+):" + JsText.Space + "*(.*)$", JsText.Options(false));
    private static readonly Regex SectionHead = new("^##" + JsText.Space + "+(.+?)" + JsText.Space + "*$", JsText.Options(false));
    private static readonly Regex AnySection = new("^##" + JsText.Space, JsText.Options(false));
    private static readonly Regex Bullet = new("^- ", JsText.Options(false));
    private static readonly Regex Numbered = new(@"^\d+\." + JsText.Space + "*", JsText.Options(false));

    /// <summary>Parse SKILL.md back to frontmatter (as JSON, since it is not validated here) and body.</summary>
    public static (JsonObject Frontmatter, SkillBody Body) Parse(string text)
    {
        var m = Document.Match(text);
        if (!m.Success)
            throw new FormatException("Invalid SKILL.md: missing YAML frontmatter delimited by ---.");
        var fm = new JsonObject();
        string? parent = null;
        foreach (var line in m.Groups[1].Value.Split('\n'))
        {
            var lm = FrontLine.Match(line);
            if (!lm.Success)
                continue;
            var indent = lm.Groups[1].Value.Length;
            var key = lm.Groups[2].Value;
            var raw = JsText.Trim(lm.Groups[3].Value);
            JsonNode? value = raw.StartsWith('[') || raw.StartsWith('{') || (raw.StartsWith('"') && raw.EndsWith('"') && raw.Length >= 2) ? JsonNode.Parse(raw) : JsonValue.Create(raw);
            if (indent == 0)
            {
                if (value is null || (value is JsonValue v && v.TryGetValue<string>(out var s) && s.Length == 0))
                {
                    fm[key] = new JsonObject();
                    parent = key;
                }
                else
                {
                    fm[key] = value;
                    parent = null;
                }
            }
            else if (parent is not null)
            {
                ((JsonObject)fm[parent]!)[key] = value;
            }
        }

        var lines = m.Groups[2].Value.Split('\n');
        var first = Array.FindIndex(lines, l => AnySection.IsMatch(l));
        var head = (first == -1 ? lines : lines[..first]).Where(l => l.Length > 0).ToList();
        var title = head.Count > 0 && head[0].StartsWith("# ", StringComparison.Ordinal) ? JsText.Trim(head[0][2..]) : "";
        var intro = JsText.Trim(string.Join("\n", head.Skip(1)));
        List<string> whenToUse = [], procedure = [];
        List<string>? prerequisites = null, pitfalls = null, quickRef = null;
        string? howToRun = null, verification = null;
        string? current = null;
        var buffer = new List<string>();
        void Flush()
        {
            if (current is null)
                return;
            var content = JsText.Trim(string.Join("\n", buffer));
            List<string> Items(Regex strip) => content.Split('\n').Select(s => strip.Replace(s, "", 1)).Where(s => s.Length > 0).ToList();
            switch (current)
            {
                case "When to Use": whenToUse = Items(Bullet); break;
                case "Prerequisites": prerequisites = Items(Bullet); break;
                case "Pitfalls": pitfalls = Items(Bullet); break;
                case "Quick Reference": quickRef = Items(Bullet); break;
                case "Procedure": procedure = Items(Numbered); break;
                case "How to Run": howToRun = content; break;
                case "Verification": verification = content; break;
            }
        }
        for (var i = first == -1 ? lines.Length : first; i < lines.Length; i++)
        {
            var sec = SectionHead.Match(lines[i]);
            if (sec.Success)
            {
                Flush();
                current = JsText.Trim(sec.Groups[1].Value);
                buffer = [];
            }
            else if (current is not null)
            {
                buffer.Add(lines[i]);
            }
        }
        Flush();
        return (fm, new SkillBody(title, whenToUse, procedure, intro.Length > 0 ? intro : null, prerequisites, howToRun, quickRef, pitfalls, verification));
    }
}
