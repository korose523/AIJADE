using System.Buffers;
using System.Text.RegularExpressions;

namespace Aijade.Client.Chat;

/// <summary>Recognize a narrow Chinese request for an expressive cue without editing the reply or prompting the model again.</summary>
internal static partial class SadnessCue
{
    private static readonly SearchValues<char> ClauseEnds = SearchValues.Create("，,。！？；：!?;:\n");
    private static readonly SearchValues<char> Quotation = SearchValues.Create("“”「」『』\"`");
    private static readonly string[] LiteralOrReportedContext =
        ["逐字", "原样", "照读", "照抄", "复述", "纯文字", "只用文字", "保持中性", "如果", "假如", "比如", "示例", "引用", "剧本", "台词", "小说人物"];

    [GeneratedRegex(@"^我(?:今天|现在|此刻|这会儿|心里|真的|其实|感到|觉得|感觉|有点|有些|还是|很|挺|特别|非常)*(?:难过|伤心|悲伤)(?:了|啊|呀)?$",
        RegexOptions.CultureInvariant | RegexOptions.NonBacktracking)]
    private static partial Regex DirectSadness();

    [GeneratedRegex(@"(?:不要|不用|不必|别|省去|省略|禁止|无需)\s*(?:加上?|添加|使用|用|输出|发|做|带)?\s*(?:任何)?\s*(?:表情|情绪标记|标记|流泪)",
        RegexOptions.CultureInvariant | RegexOptions.NonBacktracking)]
    private static partial Regex ExplicitOptOut();

    [GeneratedRegex(@"(?:^|[。！？；\n])\s*请在回复开头(?:加上?|添加)\s*\[\[emote:sad\]\]\s*作为表情标记(?:$|[，,。！？；\s])",
        RegexOptions.CultureInvariant | RegexOptions.NonBacktracking)]
    private static partial Regex ExplicitSadRequest();

    public static bool IsRequested(ChatInput input)
    {
        if (!input.UseSadnessCueFallback || input.JsonOnly || input.Speaker is not null)
            return false;
        var text = input.Text.Trim();
        if (text.AsSpan().IndexOfAny(Quotation) >= 0 || LiteralOrReportedContext.Any(phrase => text.Contains(phrase, StringComparison.Ordinal)) ||
            ExplicitOptOut().IsMatch(text))
            return false;
        var end = text.AsSpan().IndexOfAny(ClauseEnds);
        var selfReport = end < 0 || text[end] is not ('？' or '?');
        return (selfReport && DirectSadness().IsMatch(end < 0 ? text : text[..end].Trim())) || ExplicitSadRequest().IsMatch(text);
    }
}
