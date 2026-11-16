namespace Aijade.Integrations.Minecraft;

// What the companion knows about the world around it, from the server's packets (Java Edition 26.3):
//   blocks    chunk data (paletted containers) kept per 16×16×16 section, then block and section updates
//   entities  spawned entities with their positions, kept current by the movement, sync and teleport packets
// Block ids are block-state ids from the server's global palette. Only "is it air" and "is it fluid" are known
// (the ids below are fixed by the game's registry for this version); every other block is treated as solid, which keeps
// paths conservative (a flower or tall grass is walked around, not through).

/// <summary>A block position.</summary>
public readonly record struct BlockPos(int X, int Y, int Z)
{
    public BlockPos Up(int n = 1) => this with { Y = Y + n };

    public BlockPos Down(int n = 1) => this with { Y = Y - n };

    public BlockPos Offset(int dx, int dy, int dz) => new(X + dx, Y + dy, Z + dz);

    public static BlockPos Of(double x, double y, double z) => new((int)Math.Floor(x), (int)Math.Floor(y), (int)Math.Floor(z));

    /// <summary>The protocol's packed position: x 26 bits, z 26 bits, y 12 bits.</summary>
    public long Packed => ((long)(X & 0x3FFFFFF) << 38) | ((long)(Z & 0x3FFFFFF) << 12) | (long)(Y & 0xFFF);

    public static BlockPos Unpack(long v) => new((int)(v >> 38), (int)(v << 52 >> 52), (int)(v << 26 >> 38));

    public override string ToString() => $"{X} {Y} {Z}";
}

/// <summary>An entity the client has seen: its id, UUID, registry type and position.</summary>
public sealed class McEntity(int id, Guid uuid, int type, double x, double y, double z)
{
    public int Id { get; } = id;

    public Guid Uuid { get; } = uuid;

    public int Type { get; } = type;

    public double X { get; set; } = x;

    public double Y { get; set; } = y;

    public double Z { get; set; } = z;
}

public sealed class McWorld
{
    /// <summary>Block-state ids of air, void air and cave air (26.3).</summary>
    public static readonly IReadOnlySet<int> Air = new HashSet<int> { 0, 18649, 18650 };

    /// <summary>Water and lava states (26.3): not walkable, not solid ground.</summary>
    public const int FluidFirst = 89, FluidLast = 120;

    /// <summary>Entity type id of a player (26.3).</summary>
    public const int PlayerType = 159;

    /// <summary>Entity type id of a dropped item (26.3).</summary>
    public const int ItemType = 72;

    /// <summary>Entity type ids of the creatures the companion can be asked to attack (26.3), by English and Chinese name.</summary>
    public static readonly IReadOnlyDictionary<string, int> Creatures = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
    {
        ["pig"] = 101, ["猪"] = 101, ["cow"] = 30, ["牛"] = 30, ["sheep"] = 114, ["羊"] = 114, ["chicken"] = 26, ["鸡"] = 26,
        ["zombie"] = 154, ["僵尸"] = 154, ["skeleton"] = 118, ["骷髅"] = 118, ["creeper"] = 32, ["苦力怕"] = 32,
        ["spider"] = 127, ["蜘蛛"] = 127, ["slime"] = 120, ["史莱姆"] = 120,
    };

    /// <summary>Bits per entry of the global block-state palette (35 723 states in 26.3).</summary>
    public const int GlobalBlockBits = 16;

    /// <summary>The overworld's vertical extent (26.3 default dimension type, also for flat worlds).</summary>
    public int MinY { get; init; } = -64;

    public int Height { get; init; } = 384;

    private readonly Dictionary<(int, int), Section?[]> chunks = [];
    private readonly Dictionary<int, McEntity> entities = [];
    private readonly Lock gate = new();

    /// <summary>A section: one id for all 4096 blocks, or the ids in y-z-x order.</summary>
    private sealed class Section(int single, ushort[]? blocks)
    {
        public int Single = single;
        public ushort[]? Blocks = blocks;

        public int Get(int i) => Blocks is null ? Single : Blocks[i];

        public void Set(int i, int id)
        {
            if (Blocks is null)
            {
                if (id == Single)
                    return;
                Blocks = new ushort[4096];
                Array.Fill(Blocks, (ushort)Single);
            }
            Blocks[i] = (ushort)id;
        }
    }

    public event Action<BlockPos, int>? BlockChanged;

    public static bool IsAir(int id) => Air.Contains(id);

    public static bool IsFluid(int id) => id is >= FluidFirst and <= FluidLast;

    /// <summary>Water a player swims in (26.3): the water states, and the underwater plants and bubble columns that fill water.</summary>
    public static bool IsWater(int id) => id is >= 89 and <= 104 or 2370 or >= 18419 and <= 18445 or 18651 or 18652;

    /// <summary>Lava (26.3 states 105–120): never entered.</summary>
    public static bool IsLava(int id) => id is >= 105 and <= 120;

    /// <summary>Blocks a player climbs (26.3): ladders and vines.</summary>
    public static bool IsClimbable(int id) => id is >= 7307 and <= 7314 or >= 10092 and <= 10123;

    /// <summary>A block the body can occupy: air, water (swimming) or a climbable block.</summary>
    public static bool IsPassable(int id) => IsAir(id) || IsWater(id) || IsClimbable(id);

    /// <summary>Ground one can stand on: known, not air, not fluid, not water plants, not a climbable block.</summary>
    public static bool IsSolid(int id) => id >= 0 && !IsAir(id) && !IsFluid(id) && !IsWater(id) && !IsClimbable(id);

    /// <summary>The block-state id at a position, or -1 when its chunk is not loaded.</summary>
    public int BlockAt(BlockPos p)
    {
        var sy = (p.Y - MinY) >> 4;
        if (sy < 0 || p.Y - MinY >= Height)
            return 0; // above or below the world: nothing there
        lock (gate)
        {
            if (!chunks.TryGetValue((p.X >> 4, p.Z >> 4), out var sections))
                return -1;
            return sections[sy]?.Get(Index(p)) ?? 0;
        }
    }

    private int Index(BlockPos p) => (((p.Y - MinY) & 15) << 8) | ((p.Z & 15) << 4) | (p.X & 15);

    public bool IsLoaded(int chunkX, int chunkZ)
    {
        lock (gate)
            return chunks.ContainsKey((chunkX, chunkZ));
    }

    public void SetBlock(BlockPos p, int id)
    {
        var sy = (p.Y - MinY) >> 4;
        if (sy < 0 || p.Y - MinY >= Height)
            return;
        lock (gate)
        {
            if (!chunks.TryGetValue((p.X >> 4, p.Z >> 4), out var sections))
                return;
            (sections[sy] ??= new Section(0, null)).Set(Index(p), id);
        }
        BlockChanged?.Invoke(p, id);
    }

    public void Unload(int chunkX, int chunkZ)
    {
        lock (gate)
            chunks.Remove((chunkX, chunkZ));
    }

    /// <summary>
    /// Chunk Data and Update Light: chunk x, z, heightmaps, the section data, block entities and light (ignored). Each
    /// section is a non-air block count, a fluid count, a block-state paletted container and a biome paletted container.
    /// </summary>
    public void LoadChunk(McReader r)
    {
        var cx = r.Int();
        var cz = r.Int();
        var heightmaps = r.VarInt();
        for (var i = 0; i < heightmaps; i++)
        {
            r.VarInt();                // heightmap type
            r.Take(r.VarInt() * 8);    // packed heights
        }
        var size = r.VarInt();
        var data = new McReader(r.Take(size).ToArray());
        var sections = new Section?[Height >> 4];
        for (var s = 0; s < sections.Length; s++)
        {
            data.Short(); // non-air block count
            data.Short(); // fluid count
            sections[s] = ReadContainer(data, 4096, 4, 8, GlobalBlockBits);
            ReadContainer(data, 64, 1, 3, 7); // biomes (not kept)
        }
        lock (gate)
            chunks[(cx, cz)] = sections;
    }

    /// <summary>
    /// A paletted container (26.3): bits per entry; 0 = one value for all; indirect = a palette of VarInts; direct = global
    /// ids. The packed longs follow without a length prefix (entries never span two longs).
    /// </summary>
    private static Section ReadContainer(McReader r, int entries, int minIndirect, int maxIndirect, int directBits)
    {
        int bits = r.Byte();
        if (bits == 0)
            return new Section(r.VarInt(), null);
        int[]? palette = null;
        if (bits <= maxIndirect)
        {
            bits = Math.Max(bits, minIndirect);
            palette = new int[r.VarInt()];
            for (var i = 0; i < palette.Length; i++)
                palette[i] = r.VarInt();
        }
        else
        {
            bits = directBits;
        }
        var perLong = 64 / bits;
        var longs = (entries + perLong - 1) / perLong;
        var mask = (1UL << bits) - 1;
        var values = entries == 4096 ? new ushort[4096] : null;
        var index = 0;
        for (var l = 0; l < longs; l++)
        {
            var word = (ulong)r.Long();
            for (var k = 0; k < perLong && index < entries; k++, index++)
            {
                var v = (int)((word >> (k * bits)) & mask);
                if (values is not null)
                    values[index] = (ushort)(palette is null ? v : v < palette.Length ? palette[v] : 0);
            }
        }
        return new Section(0, values);
    }

    /// <summary>Section Blocks Update: a packed section position, then VarLongs of (state id &lt;&lt; 12 | local x z y).</summary>
    public void UpdateSection(McReader r)
    {
        var packed = r.Long();
        int sx = (int)(packed >> 42), sy = (int)(packed << 44 >> 44), sz = (int)(packed << 22 >> 42);
        var n = r.VarInt();
        for (var i = 0; i < n; i++)
        {
            var v = r.VarLong();
            var local = (int)(v & 0xFFF);
            SetBlock(new BlockPos((sx << 4) + (local >> 8), (sy << 4) + (local & 15), (sz << 4) + ((local >> 4) & 15)), (int)(v >> 12));
        }
    }

    // ---- entities ----------------------------------------------------------------------------------------------------

    public void AddEntity(McEntity e)
    {
        lock (gate)
            entities[e.Id] = e;
    }

    public void RemoveEntity(int id)
    {
        lock (gate)
            entities.Remove(id);
    }

    public McEntity? Entity(int id)
    {
        lock (gate)
            return entities.GetValueOrDefault(id);
    }

    /// <summary>The entities of one registry type that the client currently sees.</summary>
    public IReadOnlyList<McEntity> Entities(int type)
    {
        lock (gate)
            return entities.Values.Where(e => e.Type == type).ToList();
    }

    public McEntity? EntityByUuid(Guid uuid)
    {
        lock (gate)
            return entities.Values.FirstOrDefault(e => e.Uuid == uuid);
    }

    public void MoveEntity(int id, double dx, double dy, double dz)
    {
        lock (gate)
        {
            if (entities.TryGetValue(id, out var e))
            {
                e.X += dx;
                e.Y += dy;
                e.Z += dz;
            }
        }
    }

    public void PlaceEntity(int id, double x, double y, double z)
    {
        lock (gate)
        {
            if (entities.TryGetValue(id, out var e))
            {
                e.X = x;
                e.Y = y;
                e.Z = z;
            }
        }
    }

    // ---- paths -------------------------------------------------------------------------------------------------------

    /// <summary>
    /// A player can hold a position with its feet at <paramref name="feet"/>: two blocks the body can occupy, and either solid
    /// ground below, water at the feet (swimming) or a climbable block at the feet (on a ladder or vine).
    /// </summary>
    public bool CanStand(BlockPos feet)
    {
        int at = BlockAt(feet), head = BlockAt(feet.Up());
        return IsPassable(at) && IsPassable(head) && (IsSolid(BlockAt(feet.Down())) || IsWater(at) || IsClimbable(at));
    }

    /// <summary>Whether a position is held by swimming or climbing rather than standing (moves there are slower).</summary>
    public bool IsSwimOrClimb(BlockPos feet)
    {
        var at = BlockAt(feet);
        return IsWater(at) || IsClimbable(at);
    }

    /// <summary>
    /// A* over standing positions: walk to the four neighbours on the same level, step up one block (with head room), drop
    /// up to three, or move straight up or down while swimming or climbing. Moves through water cost twice as much. Returns the positions after <paramref name="from"/>, ending within <paramref name="near"/> blocks
    /// (horizontal) of <paramref name="to"/>; null when no path is found within the search budget.
    /// </summary>
    public IReadOnlyList<BlockPos>? FindPath(BlockPos from, BlockPos to, double near = 0, int maxNodes = 20_000)
    {
        static double H(BlockPos a, BlockPos b) => Math.Abs(a.X - b.X) + Math.Abs(a.Y - b.Y) + Math.Abs(a.Z - b.Z);
        bool Goal(BlockPos p) => near <= 0 ? p == to : Math.Sqrt(Math.Pow(p.X - to.X, 2) + Math.Pow(p.Z - to.Z, 2)) <= near && Math.Abs(p.Y - to.Y) <= 2;
        var open = new PriorityQueue<BlockPos, double>();
        var cost = new Dictionary<BlockPos, double> { [from] = 0 };
        var came = new Dictionary<BlockPos, BlockPos>();
        open.Enqueue(from, H(from, to));
        var expanded = 0;
        (int, int)[] dirs = [(1, 0), (-1, 0), (0, 1), (0, -1)];
        while (open.TryDequeue(out var p, out _))
        {
            if (Goal(p))
            {
                var path = new List<BlockPos>();
                for (var q = p; q != from; q = came[q])
                    path.Add(q);
                path.Reverse();
                return path;
            }
            if (++expanded > maxNodes)
                return null;
            foreach (var (dx, dz) in dirs)
            {
                var flat = p.Offset(dx, 0, dz);
                BlockPos? next = null;
                var step = 1.0;
                if (CanStand(flat))
                    next = flat;
                else if (CanStand(flat.Up()) && IsPassable(BlockAt(p.Up(2))))
                {
                    next = flat.Up(); // step up: needs head room above the current position for the jump
                    step = 2;
                }
                else if (IsPassable(BlockAt(flat)) && IsPassable(BlockAt(flat.Up())))
                {
                    for (var drop = 1; drop <= 3; drop++)
                    {
                        if (CanStand(flat.Down(drop)))
                        {
                            next = flat.Down(drop);
                            step = 1 + (0.5 * drop);
                            break;
                        }
                        if (!IsPassable(BlockAt(flat.Down(drop))))
                            break;
                    }
                }
                if (next is not { } n)
                    continue;
                if (IsWater(BlockAt(n)) || IsWater(BlockAt(p)))
                    step *= 2;
                var c = cost[p] + step;
                if (cost.TryGetValue(n, out var old) && old <= c)
                    continue;
                cost[n] = c;
                came[n] = p;
                open.Enqueue(n, c + H(n, to));
            }
            // swimming or climbing: straight up or down within water or along a ladder / vine
            foreach (var v in new[] { p.Up(), p.Down() })
            {
                if (!(IsSwimOrClimb(p) || IsSwimOrClimb(v)) || !CanStand(v) || !IsSwimOrClimb(v) && v.Y > p.Y)
                    continue;
                var c = cost[p] + (IsWater(BlockAt(v)) ? 2 : 1.5);
                if (cost.TryGetValue(v, out var old) && old <= c)
                    continue;
                cost[v] = c;
                came[v] = p;
                open.Enqueue(v, c + H(v, to));
            }
        }
        return null;
    }
}
