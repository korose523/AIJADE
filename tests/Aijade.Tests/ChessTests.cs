using System.Net;
using System.Text;
using System.Text.Json.Nodes;

using Aijade.Client.Api;
using Aijade.Client.Games;

namespace Aijade.Tests;

public class ChessTests
{
    // Reference perft counts (chessprogramming.org "Perft Results").
    [Theory]
    [InlineData(Chess.StartFen, 3, 8902)]
    [InlineData("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 2, 2039)]
    [InlineData("8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 4, 43238)]
    [InlineData("r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", 3, 9467)]
    [InlineData("rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", 3, 62379)]
    public void Move_generation_matches_reference_perft_counts(string fen, int depth, long nodes)
    {
        var chess = new Chess(fen);
        Assert.Equal(nodes, chess.Perft(depth));
        Assert.Equal(fen, chess.Fen()); // make / undo leaves the position exactly as it was
    }

    [Fact]
    public void San_fen_and_game_endings()
    {
        var c = new Chess();
        foreach (var m in new[] { "e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6" })
            c.Play(m);
        Assert.Equal("Qxf7#", c.Play("h5f7"));
        Assert.Equal(GameStatus.Checkmate, c.Status);
        Assert.Equal(["e4", "e5", "Bc4", "Nc6", "Qh5", "Nf6", "Qxf7#"], c.SanHistory);
        Assert.Throws<ArgumentException>(() => new Chess().Play("e5"));

        var castle = new Chess("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1");
        Assert.Equal("O-O-O", castle.Play("O-O-O"));
        Assert.Equal("r3k2r/8/8/8/8/8/8/2KR3R b kq - 1 1", castle.Fen());
        castle.TakeBack();
        Assert.Equal("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1", castle.Fen());

        var ep = new Chess("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1");
        Assert.Equal("exd6", ep.Play("exd6"));
        Assert.Equal('\0', ep["d5"]);
        var promo = new Chess("8/P7/8/8/8/8/8/k6K w - - 0 1");
        Assert.Equal("a8=N", promo.Play("a7a8n"));
        Assert.Equal('N', promo["a8"]);

        // Two knights could both reach d2: the file tells them apart.
        Assert.Equal("Nbd2", new Chess("4k3/8/8/8/8/5N2/8/1N2K3 w - - 0 1").Play("b1d2"));
        Assert.Equal(GameStatus.Stalemate, new Chess("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1").Status);
        Assert.Equal(GameStatus.InsufficientMaterial, new Chess("8/8/4k3/8/8/3NK3/8/8 w - - 0 1").Status);
        var repeat = new Chess();
        foreach (var m in new[] { "Nf3", "Nf6", "Ng1", "Ng8", "Nf3", "Nf6", "Ng1", "Ng8" })
            repeat.Play(m);
        Assert.Equal(GameStatus.Repetition, repeat.Status);
    }

    [Fact]
    public void The_helper_engine_takes_a_free_queen_and_finds_mate_in_one()
    {
        Assert.Equal("d5", Chess.SquareName(new Chess("4k3/8/8/3q4/4P3/8/8/4K3 w - - 0 1").BestMove().To));
        var mate = new Chess("6k1/5ppp/8/8/8/8/5PPP/3R2K1 w - - 0 1");
        Assert.Equal("Rd8#", mate.San(mate.BestMove()));
    }

    private sealed class Replies(params string[] texts) : HttpMessageHandler
    {
        private int i;

        public List<JsonNode> Requests { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Requests.Add(JsonNode.Parse(await request.Content!.ReadAsStringAsync(cancellationToken))!);
            var text = texts[Math.Min(i++, texts.Length - 1)];
            var body = new JsonObject { ["choices"] = new JsonArray(new JsonObject { ["message"] = new JsonObject { ["role"] = "assistant", ["content"] = text } }) };
            return new HttpResponseMessage(HttpStatusCode.OK) { Content = new StringContent(body.ToJsonString(), Encoding.UTF8, "application/json") };
        }
    }

    private static ChessCompanion Companion(Replies llm) =>
        new(new AijadeApi(new HttpClient(llm) { BaseAddress = new Uri("http://aijade.test/") }, new MemoryTokenStore()), () => "aijade-chat");

    [Fact]
    public async Task The_companion_moves_in_character_retries_an_illegal_move_and_admits_engine_help()
    {
        var ct = TestContext.Current.CancellationToken;
        var game = new Game(Side.Black, "italian");
        Assert.True(game.CompanionToMove);
        var good = new Replies("[[emote:curious]]The Italian! [[move:Bc5]] I will mirror your bishop.");
        var m = await Companion(good).MoveAsync(game, null, ct);
        Assert.Equal(("Bc5", "The Italian!  I will mirror your bishop.", false), (m.San, m.Comment, m.ByEngine));
        Assert.Equal(["curious"], m.Expressions);
        var prompt = good.Requests[0]["messages"]![1]!["content"]!.GetValue<string>();
        Assert.Contains("1. e4 e5 2. Nf3 Nc6 3. Bc4", prompt, StringComparison.Ordinal);
        Assert.Contains("Your legal moves:", prompt, StringComparison.Ordinal);

        game.Board.Play("c3");
        var retry = new Replies("[[move:Qxf2]] Bold!", "Sorry. [[move:Nf6]]");
        Assert.Equal(("Nf6", false), (await Companion(retry).MoveAsync(game, null, ct)) is var r ? (r.San, r.ByEngine) : default);
        Assert.Contains("\"Qxf2\" is not legal here.", retry.Requests[1]["messages"]!.AsArray()[^1]!["content"]!.GetValue<string>(), StringComparison.Ordinal);

        game.Board.Play("d4");
        var engine = await Companion(new Replies("I'd rather chat.", "still no move")).MoveAsync(game, null, ct);
        Assert.True(engine.ByEngine);
        Assert.Equal(Side.White, game.Board.Turn);
    }
}
