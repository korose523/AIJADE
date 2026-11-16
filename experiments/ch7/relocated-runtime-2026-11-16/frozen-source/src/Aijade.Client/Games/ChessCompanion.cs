using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Chat;

namespace Aijade.Client.Games;

/// <summary>The companion's move and what it says about it. <see cref="ByEngine"/>: the model did not give a legal move.</summary>
public sealed record CompanionMove(string San, string Comment, IReadOnlyList<string> Expressions, bool ByEngine);

/// <summary>
/// The companion plays chess: it gets the position, the move history and every legal move, answers in character with a
/// [[move:…]] marker, and a move that is missing or illegal is asked for once more with the reason; after that the helper
/// engine plays, and the result says so (the user is never told the companion chose a move it did not choose).
/// </summary>
public sealed class ChessCompanion(AijadeApi api, Func<string> model)
{
    public static readonly IReadOnlyDictionary<string, string[]> Openings = new Dictionary<string, string[]>(StringComparer.Ordinal)
    {
        ["standard"] = [], ["queen-gambit"] = ["d4", "d5", "c4"], ["italian"] = ["e4", "e5", "Nf3", "Nc6", "Bc4"], ["sicilian"] = ["e4", "c5"], ["french"] = ["e4", "e6"],
    };

    public static string Prompt(Chess game, Side companionSide)
    {
        var legal = game.LegalMoves().Select(game.San).ToList();
        var history = game.SanHistory;
        return $"""
            We are playing chess. You play {companionSide.ToString().ToLowerInvariant()}.
            Moves so far: {(history.Count == 0 ? "none" : string.Join(' ', history.Select((m, i) => i % 2 == 0 ? $"{(i / 2) + 1}. {m}" : m)))}
            Position (FEN): {game.Fen()}
            Your legal moves: {string.Join(", ", legal)}
            Choose one of them and write it as [[move:SAN]] (for example [[move:{legal[0]}]]), then say one or two short sentences to me about the game, in character.
            """;
    }

    public async Task<CompanionMove> MoveAsync(Game game, Character? character, CancellationToken ct = default)
    {
        var system = ChatOrchestrator.SystemPrompt(character, []);
        var messages = new JsonArray(new JsonObject { ["role"] = "system", ["content"] = system }, new JsonObject { ["role"] = "user", ["content"] = Prompt(game.Board, game.CompanionSide) });
        for (var attempt = 0; attempt < 2; attempt++)
        {
            string text;
            try
            {
                text = Aijade.Providers.Llm.ChatParsing.ParseCompletion(await api.CompleteChatAsync(model(), messages, ct: ct).ConfigureAwait(false), model()).Text;
            }
            catch (AijadeApiException)
            {
                break; // model unavailable: the engine keeps the game going
            }
            var parser = new MarkerParser("move", "emote");
            var (visible, markers) = parser.Feed(text);
            visible += parser.Flush();
            var move = markers.FirstOrDefault(m => m.Kind == "move")?.Value;
            var emotes = markers.Where(m => m.Kind == "emote").Select(m => m.Value).ToList();
            if (move is not null)
            {
                try
                {
                    return new CompanionMove(game.Board.Play(move), visible.Trim(), emotes, false);
                }
                catch (ArgumentException)
                {
                    // fall through to ask again
                }
            }
            messages.Add(new JsonObject { ["role"] = "assistant", ["content"] = text });
            messages.Add(new JsonObject
            {
                ["role"] = "user",
                ["content"] = $"{(move is null ? "I could not find a [[move:…]] marker." : $"\"{move}\" is not legal here.")} Legal moves: {string.Join(", ", game.Board.LegalMoves().Select(game.Board.San))}. Answer with [[move:SAN]] again.",
            });
        }
        var san = game.Board.Play(game.Board.BestMove().Uci);
        return new CompanionMove(san, "", [], true);
    }
}

/// <summary>A game in progress: the board and which side the companion plays.</summary>
public sealed class Game(Side companionSide, string opening = "standard")
{
    public Chess Board { get; } = Start(opening);

    public Side CompanionSide { get; } = companionSide;

    public bool CompanionToMove => Board.Status == GameStatus.Playing && Board.Turn == CompanionSide;

    private static Chess Start(string opening)
    {
        var board = new Chess();
        foreach (var m in ChessCompanion.Openings.TryGetValue(opening, out var line) ? line : [])
            board.Play(m);
        return board;
    }
}
