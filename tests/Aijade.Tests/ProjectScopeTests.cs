using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Xml.Linq;

namespace Aijade.Tests;

/// <summary>
/// The research line must not depend on the non-research line (docs/PROJECT-SCOPE.md, docs/decisions/ADR-001.md).
/// configs/project-scope.json assigns every module to a line and says which lines each line may reference; these checks
/// hold the directory tree and the project references to it. They are static: they say nothing about whether a study's
/// results hold, and a dynamic call (HTTP, files) between lines is not seen by them.
/// </summary>
public class ProjectScopeTests
{
    private sealed record Module(string Path, string Line, IReadOnlyList<string> ResearchObjects);

    private sealed record Frozen(string Path, string Sha256, string Until);

    private sealed record Scope(IReadOnlyDictionary<string, string[]> Lines, IReadOnlyList<Module> Modules, IReadOnlyList<Frozen> Frozen);

    /// <summary>Directories whose immediate subdirectories are modules.</summary>
    private static readonly string[] ModuleParents = ["src", "tools", "tests", "integrations"];

    /// <summary>Directories that hold build output or dependencies, never sources.</summary>
    private static readonly string[] Skipped = ["bin", "obj", "node_modules", ".git"];

    private static readonly string Root = RqcReanalysisTests.RepoRoot();

    private static Scope Load()
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(Root, "configs", "project-scope.json")));
        var lines = doc.RootElement.GetProperty("lines").EnumerateObject().ToDictionary(
            p => p.Name,
            p => p.Value.GetProperty("mayReference").EnumerateArray().Select(e => e.GetString()!).ToArray(),
            StringComparer.Ordinal);
        var modules = doc.RootElement.GetProperty("modules").EnumerateArray().Select(m => new Module(
            m.GetProperty("path").GetString()!,
            m.GetProperty("line").GetString()!,
            m.TryGetProperty("researchObjects", out var r) ? r.EnumerateArray().Select(e => e.GetString()!).ToArray() : []))
            .ToList();
        var frozen = doc.RootElement.TryGetProperty("frozen", out var f)
            ? f.EnumerateArray().Select(e => new Frozen(e.GetProperty("path").GetString()!, e.GetProperty("sha256").GetString()!, e.GetProperty("until").GetString()!)).ToList()
            : [];
        return new Scope(lines, modules, frozen);
    }

    /// <summary>SHA-256 of a file's text with line endings normalized to LF, so a checkout's line-ending setting does not count.</summary>
    private static string TextHash(string relative) => Convert.ToHexStringLower(
        SHA256.HashData(Encoding.UTF8.GetBytes(File.ReadAllText(Path.Combine(Root, relative)).Replace("\r\n", "\n", StringComparison.Ordinal))));

    private static string Relative(string fullPath) => Path.GetRelativePath(Root, fullPath).Replace('\\', '/');

    /// <summary>The module that contains a repository-relative path: the longest declared path that is a prefix of it.</summary>
    private static Module? Owner(Scope scope, string relative) => scope.Modules
        .Where(m => string.Equals(relative, m.Path, StringComparison.Ordinal) || relative.StartsWith(m.Path + "/", StringComparison.Ordinal))
        .MaxBy(m => m.Path.Length);

    private static IEnumerable<string> ProjectFiles(string directory)
    {
        foreach (var file in Directory.EnumerateFiles(directory, "*.csproj"))
            yield return file;
        foreach (var sub in Directory.EnumerateDirectories(directory))
        {
            if (Skipped.Contains(Path.GetFileName(sub), StringComparer.Ordinal))
                continue;
            foreach (var file in ProjectFiles(sub))
                yield return file;
        }
    }

    [Fact]
    public void Every_declared_module_exists_on_a_known_line()
    {
        var scope = Load();
        foreach (var (line, mayReference) in scope.Lines)
            Assert.All(mayReference, target => Assert.True(scope.Lines.ContainsKey(target), $"line {line} may reference unknown line {target}"));
        Assert.Equal(scope.Modules.Count, scope.Modules.Select(m => m.Path).Distinct(StringComparer.Ordinal).Count());
        Assert.All(scope.Modules, m =>
        {
            Assert.True(scope.Lines.ContainsKey(m.Line), $"{m.Path}: unknown line {m.Line}");
            Assert.True(Directory.Exists(Path.Combine(Root, m.Path)), $"{m.Path}: declared but missing");
            Assert.All(m.ResearchObjects, o =>
            {
                Assert.StartsWith(m.Path + "/", o, StringComparison.Ordinal);
                Assert.True(File.Exists(Path.Combine(Root, o)) || Directory.Exists(Path.Combine(Root, o)), $"{o}: declared research object is missing");
            });
        });
    }

    [Fact]
    public void Every_module_directory_is_declared()
    {
        var scope = Load();
        var undeclared = ModuleParents
            .Select(parent => Path.Combine(Root, parent))
            .Where(Directory.Exists)
            .SelectMany(Directory.EnumerateDirectories)
            .Where(d => !Skipped.Contains(Path.GetFileName(d), StringComparer.Ordinal))
            .Select(Relative)
            .Where(relative => Owner(scope, relative) is null)
            .ToList();
        Assert.True(undeclared.Count == 0, "modules not declared in configs/project-scope.json: " + string.Join(", ", undeclared));
    }

    [Fact]
    public void Project_references_stay_within_the_lines_each_line_may_reference()
    {
        var scope = Load();
        var violations = new List<string>();
        foreach (var project in ModuleParents.Select(p => Path.Combine(Root, p)).Where(Directory.Exists).SelectMany(ProjectFiles))
        {
            var from = Owner(scope, Relative(project));
            Assert.True(from is not null, $"{Relative(project)} lies in no declared module");
            var references = XDocument.Load(project).Descendants()
                .Where(e => string.Equals(e.Name.LocalName, "ProjectReference", StringComparison.Ordinal))
                .Select(e => e.Attribute("Include")?.Value)
                .OfType<string>();
            foreach (var include in references)
            {
                var target = Relative(Path.GetFullPath(Path.Combine(Path.GetDirectoryName(project)!, include.Replace('\\', '/'))));
                var to = Owner(scope, target);
                if (to is null)
                    violations.Add($"{Relative(project)} -> {target} (undeclared)");
                else if (!scope.Lines[from.Line].Contains(to.Line, StringComparer.Ordinal))
                    violations.Add($"{from.Path} ({from.Line}) -> {to.Path} ({to.Line})");
            }
        }
        Assert.True(violations.Count == 0, "references across lines that the scope forbids: " + string.Join("; ", violations));
    }

    /// <summary>
    /// A research object that a planned study measures as it stands is frozen until that study is archived (docs/PROJECT-SCOPE.md):
    /// its text keeps the recorded hash, so work on the non-research line cannot change it unnoticed. A change that must be made is
    /// recorded in docs/STATUS.md and listed as a deviation of that study before the hash in configs/project-scope.json is updated.
    /// </summary>
    [Fact]
    public void Frozen_research_objects_keep_their_recorded_text()
    {
        var scope = Load();
        var researchObjects = scope.Modules.SelectMany(m => m.ResearchObjects).ToHashSet(StringComparer.Ordinal);
        var changed = new List<string>();
        foreach (var frozen in scope.Frozen)
        {
            Assert.True(researchObjects.Contains(frozen.Path), $"{frozen.Path}: frozen but not declared as a research object");
            var hash = TextHash(frozen.Path);
            if (!string.Equals(hash, frozen.Sha256, StringComparison.Ordinal))
                changed.Add($"{frozen.Path} (frozen until {frozen.Until}; its text now hashes to {hash})");
        }
        Assert.True(changed.Count == 0, "frozen research objects changed: " + string.Join("; ", changed));
    }
}
