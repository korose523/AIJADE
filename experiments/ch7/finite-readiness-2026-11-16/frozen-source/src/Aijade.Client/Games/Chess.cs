using System.Globalization;
using System.Text;

namespace Aijade.Client.Games;

// Chess for the companion's game corner: complete rules (castling, en passant, promotion; checkmate, stalemate, the
// fifty-move rule, threefold repetition, insufficient material), FEN in and out, SAN in and out (coordinates such as
// "g1f3" / "e7e8q" are accepted too). Board squares are 0..63 from a1 = 0 to h8 = 63. Verified with perft counts.

public enum Side
{
    White,
    Black,
}

public enum GameStatus
{
    Playing,
    Checkmate,
    Stalemate,
    FiftyMoves,
    Repetition,
    InsufficientMaterial,
}

public readonly record struct Move(int From, int To, char Promotion = '\0')
{
    public string Uci => $"{Chess.SquareName(From)}{Chess.SquareName(To)}{(Promotion == '\0' ? "" : char.ToLowerInvariant(Promotion).ToString())}";
}

public sealed class Chess
{
    public const string StartFen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1";

    private readonly char[] board = new char[64]; // 'P','N',… white, 'p','n',… black, '\0' empty
    private readonly List<(Move Move, char Captured, string Castling, int EnPassant, int Halfmove, string San)> history = [];
    private readonly List<string> positions = [];

    public Side Turn { get; private set; }

    /// <summary>"KQkq" subset, "" when none.</summary>
    public string Castling { get; private set; } = "";

    /// <summary>The en-passant target square, or -1.</summary>
    public int EnPassant { get; private set; } = -1;

    public int Halfmove { get; private set; }

    public int Fullmove { get; private set; } = 1;

    public IReadOnlyList<string> SanHistory => [.. history.Select(h => h.San)];

    public Move? LastMove => history.Count == 0 ? null : history[^1].Move;

    public Chess(string fen = StartFen) => Load(fen);

    public static string SquareName(int sq) => $"{(char)('a' + (sq % 8))}{(char)('1' + (sq / 8))}";

    public static int Square(string name) =>
        name.Length == 2 && name[0] is >= 'a' and <= 'h' && name[1] is >= '1' and <= '8' ? ((name[1] - '1') * 8) + (name[0] - 'a') : throw new FormatException($"bad square '{name}'");

    public char this[int square] => board[square];

    public char this[string square] => board[Square(square)];

    private static bool IsWhite(char p) => p is >= 'A' and <= 'Z';

    private static Side SideOf(char p) => IsWhite(p) ? Side.White : Side.Black;

    private static char Upper(char p) => char.ToUpperInvariant(p);

    private void Load(string fen)
    {
        var f = fen.Trim().Split(' ', StringSplitOptions.RemoveEmptyEntries);
        if (f.Length < 4)
            throw new FormatException("FEN needs at least 4 fields");
        Array.Clear(board);
        var ranks = f[0].Split('/');
        if (ranks.Length != 8)
            throw new FormatException("FEN board needs 8 ranks");
        for (var r = 0; r < 8; r++)
        {
            var file = 0;
            foreach (var c in ranks[r])
            {
                if (char.IsAsciiDigit(c))
                    file += c - '0';
                else if ("PNBRQKpnbrqk".Contains(c, StringComparison.Ordinal) && file < 8)
                    board[((7 - r) * 8) + file++] = c;
                else
                    throw new FormatException($"bad FEN piece '{c}'");
            }
            if (file != 8)
                throw new FormatException("FEN rank does not have 8 files");
        }
        Turn = f[1] == "b" ? Side.Black : Side.White;
        Castling = f[2] == "-" ? "" : f[2];
        EnPassant = f[3] == "-" ? -1 : Square(f[3]);
        Halfmove = f.Length > 4 ? int.Parse(f[4], CultureInfo.InvariantCulture) : 0;
        Fullmove = f.Length > 5 ? int.Parse(f[5], CultureInfo.InvariantCulture) : 1;
        history.Clear();
        positions.Clear();
        positions.Add(PositionKey());
    }

    public string Fen()
    {
        var sb = new StringBuilder();
        for (var r = 7; r >= 0; r--)
        {
            var empty = 0;
            for (var file = 0; file < 8; file++)
            {
                var p = board[(r * 8) + file];
                if (p == '\0')
                {
                    empty++;
                    continue;
                }
                if (empty > 0)
                    sb.Append(empty);
                empty = 0;
                sb.Append(p);
            }
            if (empty > 0)
                sb.Append(empty);
            if (r > 0)
                sb.Append('/');
        }
        return $"{sb} {(Turn == Side.White ? 'w' : 'b')} {(Castling.Length == 0 ? "-" : Castling)} {(EnPassant < 0 ? "-" : SquareName(EnPassant))} {Halfmove} {Fullmove}";
    }

    private string PositionKey() => string.Join(' ', Fen().Split(' ')[..4]);

    // ---- attacks and move generation ----------------------------------------------------------------------------------

    private static readonly (int Df, int Dr)[] KnightSteps = [(1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2)];
    private static readonly (int Df, int Dr)[] KingSteps = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)];
    private static readonly (int Df, int Dr)[] Rook = [(1, 0), (-1, 0), (0, 1), (0, -1)];
    private static readonly (int Df, int Dr)[] Bishop = [(1, 1), (1, -1), (-1, 1), (-1, -1)];

    private static int Step(int sq, int df, int dr)
    {
        int f = (sq % 8) + df, r = (sq / 8) + dr;
        return f is >= 0 and < 8 && r is >= 0 and < 8 ? (r * 8) + f : -1;
    }

    /// <summary>Whether <paramref name="by"/> attacks square <paramref name="sq"/>.</summary>
    public bool Attacked(int sq, Side by)
    {
        var white = by == Side.White;
        var pawnDir = white ? -1 : 1; // look back towards the attacker's pawns
        foreach (var df in new[] { -1, 1 })
        {
            var s = Step(sq, df, pawnDir);
            if (s >= 0 && board[s] == (white ? 'P' : 'p'))
                return true;
        }
        foreach (var (df, dr) in KnightSteps)
        {
            var s = Step(sq, df, dr);
            if (s >= 0 && board[s] == (white ? 'N' : 'n'))
                return true;
        }
        foreach (var (df, dr) in KingSteps)
        {
            var s = Step(sq, df, dr);
            if (s >= 0 && board[s] == (white ? 'K' : 'k'))
                return true;
        }
        foreach (var (dirs, a, b) in new[] { (Rook, 'R', 'Q'), (Bishop, 'B', 'Q') })
        {
            foreach (var (df, dr) in dirs)
            {
                for (var s = Step(sq, df, dr); s >= 0; s = Step(s, df, dr))
                {
                    var p = board[s];
                    if (p == '\0')
                        continue;
                    if (SideOf(p) == by && (Upper(p) == a || Upper(p) == b))
                        return true;
                    break;
                }
            }
        }
        return false;
    }

    private int KingSquare(Side side) => Array.IndexOf(board, side == Side.White ? 'K' : 'k');

    public bool InCheck => KingSquare(Turn) is var k && k >= 0 && Attacked(k, Turn == Side.White ? Side.Black : Side.White);

    private IEnumerable<Move> PseudoMoves()
    {
        var white = Turn == Side.White;
        for (var sq = 0; sq < 64; sq++)
        {
            var p = board[sq];
            if (p == '\0' || IsWhite(p) != white)
                continue;
            switch (Upper(p))
            {
                case 'P':
                {
                    var dir = white ? 1 : -1;
                    var startRank = white ? 1 : 6;
                    var lastRank = white ? 7 : 0;
                    var one = Step(sq, 0, dir);
                    if (one >= 0 && board[one] == '\0')
                    {
                        foreach (var m in Promote(sq, one, lastRank))
                            yield return m;
                        var two = Step(one, 0, dir);
                        if (sq / 8 == startRank && board[two] == '\0')
                            yield return new Move(sq, two);
                    }
                    foreach (var df in new[] { -1, 1 })
                    {
                        var t = Step(sq, df, dir);
                        if (t < 0)
                            continue;
                        if ((board[t] != '\0' && IsWhite(board[t]) != white) || t == EnPassant)
                        {
                            foreach (var m in Promote(sq, t, lastRank))
                                yield return m;
                        }
                    }
                    break;
                }
                case 'N':
                case 'K':
                    foreach (var (df, dr) in Upper(p) == 'N' ? KnightSteps : KingSteps)
                    {
                        var t = Step(sq, df, dr);
                        if (t >= 0 && (board[t] == '\0' || IsWhite(board[t]) != white))
                            yield return new Move(sq, t);
                    }
                    if (Upper(p) == 'K')
                    {
                        foreach (var m in CastlingMoves())
                            yield return m;
                    }
                    break;
                default:
                    var dirs = Upper(p) switch { 'R' => Rook, 'B' => Bishop, _ => [.. Rook, .. Bishop] };
                    foreach (var (df, dr) in dirs)
                    {
                        for (var t = Step(sq, df, dr); t >= 0; t = Step(t, df, dr))
                        {
                            if (board[t] == '\0')
                            {
                                yield return new Move(sq, t);
                                continue;
                            }
                            if (IsWhite(board[t]) != white)
                                yield return new Move(sq, t);
                            break;
                        }
                    }
                    break;
            }
        }
    }

    private static IEnumerable<Move> Promote(int from, int to, int lastRank)
    {
        if (to / 8 != lastRank)
        {
            yield return new Move(from, to);
            yield break;
        }
        foreach (var piece in "QRBN")
            yield return new Move(from, to, piece);
    }

    private IEnumerable<Move> CastlingMoves()
    {
        var white = Turn == Side.White;
        var enemy = white ? Side.Black : Side.White;
        var king = white ? 4 : 60;
        if (board[king] != (white ? 'K' : 'k') || Attacked(king, enemy))
            yield break;
        if (Castling.Contains(white ? 'K' : 'k', StringComparison.Ordinal) && board[king + 1] == '\0' && board[king + 2] == '\0'
            && board[king + 3] == (white ? 'R' : 'r') && !Attacked(king + 1, enemy) && !Attacked(king + 2, enemy))
            yield return new Move(king, king + 2);
        if (Castling.Contains(white ? 'Q' : 'q', StringComparison.Ordinal) && board[king - 1] == '\0' && board[king - 2] == '\0' && board[king - 3] == '\0'
            && board[king - 4] == (white ? 'R' : 'r') && !Attacked(king - 1, enemy) && !Attacked(king - 2, enemy))
            yield return new Move(king, king - 2);
    }

    /// <summary>All legal moves of the side to move.</summary>
    public IReadOnlyList<Move> LegalMoves()
    {
        var legal = new List<Move>();
        var mover = Turn;
        foreach (var m in PseudoMoves().ToList())
        {
            Make(m, "");
            var k = KingSquare(mover);
            if (!Attacked(k, mover == Side.White ? Side.Black : Side.White))
                legal.Add(m);
            Undo();
        }
        return legal;
    }

    // ---- making moves -------------------------------------------------------------------------------------------------

    private void Make(Move m, string san)
    {
        var p = board[m.From];
        var captured = board[m.To];
        var white = IsWhite(p);
        var record = (m, captured, Castling, EnPassant, Halfmove, san);
        if (Upper(p) == 'P' && m.To == EnPassant)
        {
            var victim = m.To + (white ? -8 : 8);
            captured = board[victim];
            board[victim] = '\0';
            record.captured = captured;
        }
        board[m.To] = m.Promotion == '\0' ? p : (white ? Upper(m.Promotion) : char.ToLowerInvariant(m.Promotion));
        board[m.From] = '\0';
        if (Upper(p) == 'K' && Math.Abs(m.To - m.From) == 2)
        {
            var (rookFrom, rookTo) = m.To > m.From ? (m.From + 3, m.From + 1) : (m.From - 4, m.From - 1);
            board[rookTo] = board[rookFrom];
            board[rookFrom] = '\0';
        }
        var rights = new StringBuilder(Castling);
        void Drop(char c) => rights.Replace(c.ToString(), "");
        if (p == 'K') { Drop('K'); Drop('Q'); }
        if (p == 'k') { Drop('k'); Drop('q'); }
        foreach (var sq in new[] { m.From, m.To })
        {
            if (sq == 0) Drop('Q');
            if (sq == 7) Drop('K');
            if (sq == 56) Drop('q');
            if (sq == 63) Drop('k');
        }
        Castling = rights.ToString();
        EnPassant = Upper(p) == 'P' && Math.Abs(m.To - m.From) == 16 ? (m.From + m.To) / 2 : -1;
        Halfmove = Upper(p) == 'P' || record.captured != '\0' ? 0 : Halfmove + 1;
        if (!white)
            Fullmove++;
        Turn = white ? Side.Black : Side.White;
        history.Add(record);
        if (san.Length > 0)
            positions.Add(PositionKey()); // only real moves count for repetition; search probes do not
    }

    /// <summary>Take back the last move played.</summary>
    public void TakeBack()
    {
        if (history.Count == 0)
            throw new InvalidOperationException("no move to take back");
        positions.RemoveAt(positions.Count - 1);
        Undo();
    }

    private void Undo()
    {
        var (m, captured, castling, enPassant, halfmove, _) = history[^1];
        history.RemoveAt(history.Count - 1);
        var p = board[m.To];
        var white = IsWhite(p);
        board[m.From] = m.Promotion == '\0' ? p : (white ? 'P' : 'p');
        board[m.To] = '\0';
        if (Upper(board[m.From]) == 'P' && m.To == enPassant)
            board[m.To + (white ? -8 : 8)] = captured;
        else
            board[m.To] = captured;
        if (Upper(p) == 'K' && Math.Abs(m.To - m.From) == 2)
        {
            var (rookFrom, rookTo) = m.To > m.From ? (m.From + 3, m.From + 1) : (m.From - 4, m.From - 1);
            board[rookFrom] = board[rookTo];
            board[rookTo] = '\0';
        }
        Castling = castling;
        EnPassant = enPassant;
        Halfmove = halfmove;
        if (!white)
            Fullmove--;
        Turn = white ? Side.White : Side.Black;
    }

    /// <summary>Play a move given in SAN ("Nf3", "O-O", "exd5", "e8=Q+") or coordinates ("g1f3", "e7e8q"). Returns its SAN.</summary>
    public string Play(string move)
    {
        var legal = LegalMoves();
        var m = Parse(move, legal) ?? throw new ArgumentException($"illegal move '{move}'. Legal: {string.Join(", ", legal.Select(San))}");
        var san = San(m);
        Make(m, san);
        return san;
    }

    private Move? Parse(string text, IReadOnlyList<Move> legal)
    {
        var t = text.Trim().TrimEnd('+', '#', '!', '?').Replace("0-0", "O-O", StringComparison.Ordinal);
        if (t.Length is 4 or 5 && char.IsAsciiLetterLower(t[0]) && char.IsAsciiDigit(t[1]) && char.IsAsciiLetterLower(t[2]) && char.IsAsciiDigit(t[3]))
        {
            try
            {
                var (from, to) = (Square(t[..2]), Square(t[2..4]));
                var promo = t.Length == 5 ? char.ToUpperInvariant(t[4]) : '\0';
                var found = legal.Where(m => m.From == from && m.To == to && (m.Promotion == promo || (promo == '\0' && m.Promotion == 'Q'))).ToList();
                if (found.Count > 0)
                    return found[0];
            }
            catch (FormatException)
            {
            }
        }
        foreach (var m in legal)
        {
            if (San(m).TrimEnd('+', '#') == t)
                return m;
        }
        return null;
    }

    /// <summary>Standard algebraic notation of a legal move in the current position (with + or #).</summary>
    public string San(Move m)
    {
        var p = board[m.From];
        string core;
        if (Upper(p) == 'K' && Math.Abs(m.To - m.From) == 2)
        {
            core = m.To > m.From ? "O-O" : "O-O-O";
        }
        else
        {
            var capture = board[m.To] != '\0' || (Upper(p) == 'P' && m.To == EnPassant);
            var sb = new StringBuilder();
            if (Upper(p) == 'P')
            {
                if (capture)
                    sb.Append((char)('a' + (m.From % 8)));
            }
            else
            {
                sb.Append(Upper(p));
                var rivals = PseudoMoves().Where(o => o.To == m.To && o.From != m.From && board[o.From] == p).Where(LegalFast).ToList();
                if (rivals.Count > 0)
                {
                    var sameFile = rivals.Any(o => o.From % 8 == m.From % 8);
                    var sameRank = rivals.Any(o => o.From / 8 == m.From / 8);
                    if (!sameFile)
                        sb.Append((char)('a' + (m.From % 8)));
                    else if (!sameRank)
                        sb.Append((char)('1' + (m.From / 8)));
                    else
                        sb.Append(SquareName(m.From));
                }
            }
            if (capture)
                sb.Append('x');
            sb.Append(SquareName(m.To));
            if (m.Promotion != '\0')
                sb.Append('=').Append(m.Promotion);
            core = sb.ToString();
        }
        Make(m, "");
        var check = InCheck;
        var mate = check && LegalMoves().Count == 0;
        Undo();
        return core + (mate ? "#" : check ? "+" : "");
    }

    private bool LegalFast(Move m)
    {
        var mover = Turn;
        Make(m, "");
        var ok = !Attacked(KingSquare(mover), mover == Side.White ? Side.Black : Side.White);
        Undo();
        return ok;
    }

    public GameStatus Status
    {
        get
        {
            if (LegalMoves().Count == 0)
                return InCheck ? GameStatus.Checkmate : GameStatus.Stalemate;
            if (Halfmove >= 100)
                return GameStatus.FiftyMoves;
            if (positions.Count(p => p == positions[^1]) >= 3)
                return GameStatus.Repetition;
            var pieces = board.Where(p => p != '\0' && Upper(p) != 'K').Select(Upper).ToList();
            if (pieces.Count == 0 || (pieces.Count == 1 && pieces[0] is 'B' or 'N'))
                return GameStatus.InsufficientMaterial;
            return GameStatus.Playing;
        }
    }

    /// <summary>Count leaf positions to a depth: the standard correctness check for move generators.</summary>
    public long Perft(int depth)
    {
        if (depth == 0)
            return 1;
        var moves = LegalMoves();
        if (depth == 1)
            return moves.Count;
        long n = 0;
        foreach (var m in moves)
        {
            Make(m, "");
            n += Perft(depth - 1);
            Undo();
        }
        return n;
    }

    // ---- a small engine for when the companion needs help ---------------------------------------------------------------

    private static readonly Dictionary<char, int> Value = new() { ['P'] = 100, ['N'] = 320, ['B'] = 330, ['R'] = 500, ['Q'] = 900, ['K'] = 0 };

    private int Evaluate()
    {
        var score = 0;
        for (var sq = 0; sq < 64; sq++)
        {
            var p = board[sq];
            if (p == '\0')
                continue;
            var v = Value[Upper(p)];
            // A little central preference keeps the play natural.
            var centre = 3 - Math.Max(Math.Abs(3.5 - (sq % 8)), Math.Abs(3.5 - (sq / 8)));
            v += (int)(centre * (Upper(p) is 'N' or 'B' or 'P' ? 8 : 2));
            score += IsWhite(p) ? v : -v;
        }
        return Turn == Side.White ? score : -score;
    }

    private int Search(int depth, int alpha, int beta)
    {
        var moves = LegalMoves();
        if (moves.Count == 0)
            return InCheck ? -100_000 - depth : 0;
        if (depth == 0)
            return Evaluate();
        foreach (var m in moves.OrderByDescending(m => board[m.To] == '\0' ? 0 : Value[Upper(board[m.To])]))
        {
            Make(m, "");
            var score = -Search(depth - 1, -beta, -alpha);
            Undo();
            if (score >= beta)
                return beta;
            alpha = Math.Max(alpha, score);
        }
        return alpha;
    }

    /// <summary>A reasonable move by a shallow alpha-beta search (deterministic: ties go to the first move in order).</summary>
    public Move BestMove(int depth = 2)
    {
        var moves = LegalMoves();
        if (moves.Count == 0)
            throw new InvalidOperationException("no legal move");
        Move best = moves[0];
        var bestScore = int.MinValue;
        foreach (var m in moves)
        {
            Make(m, "");
            var score = -Search(depth - 1, -1_000_000, 1_000_000);
            Undo();
            if (score > bestScore)
            {
                bestScore = score;
                best = m;
            }
        }
        return best;
    }
}
