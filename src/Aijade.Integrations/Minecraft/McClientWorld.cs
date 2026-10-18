namespace Aijade.Integrations.Minecraft;

// The client's body in the world: it keeps the world model current from the server's packets, walks paths found in it
// (one position update per game tick, at walking speed, with small hops for steps), and digs and places blocks the way a
// player does (Player Action / Use Item On with sequence numbers; the server's block updates are the confirmation).
public sealed partial class McClient
{
    private const int CAddEntity = 0x01, CBlockChangedAck = 0x04, CBlockUpdate = 0x08, CChunkBatchFinished = 0x0B, CContainerSetContent = 0x12,
        CContainerSetSlot = 0x14, CEntityPositionSync = 0x23, CForgetChunk = 0x26, CChunk = 0x2E, CMoveEntityPos = 0x36, CMoveEntityPosRot = 0x37,
        CRemoveEntities = 0x4E, CSectionBlocksUpdate = 0x56, CSetHeldSlot = 0x6B, CSetPlayerInventory = 0x6E, CTeleportEntity = 0x80;

    // Player Action statuses (26.3 inserted "change destroy direction" at 1).
    private const int StartDigging = 0, AbortDigging = 2, FinishDigging = 3;

    private const int SAttack = 0x01, SSetCarriedItem = 0x36;

    private const int SChunkBatchReceived = 0x0B, SClientTickEnd = 0x0D, SMovePlayerPos = 0x1E, SMovePlayerPosRot = 0x1F, SPlayerAction = 0x29, SUseItemOn = 0x42;

    /// <summary>Blocks per tick when walking (vanilla walking speed is about 4.3 blocks/s = 0.215 per tick).</summary>
    public const double WalkStep = 0.2;

    /// <summary>How far a survival player can reach to dig or place.</summary>
    public const double Reach = 4.5;

    private readonly Lock motion = new();
    private bool teleported;
    private int sequence;

    public McWorld World { get; } = new();

    // The hotbar as far as the client knows it: item counts per slot (-1 = unknown) and the selected slot.
    private readonly int[] hotbar = [-1, -1, -1, -1, -1, -1, -1, -1, -1];
    private int selected;

    /// <summary>Item counts of the nine hotbar slots; -1 where the server's data could not be read.</summary>
    public IReadOnlyList<int> Hotbar
    {
        get
        {
            lock (hotbar)
                return [.. hotbar];
        }
    }

    public int SelectedSlot => selected;

    /// <summary>
    /// An item stack (26.3): count, then the item id and a component patch (added, removed). Components carry no length
    /// prefix, so a stack with added components cannot be skipped: null then means "the rest of this packet is unreadable".
    /// </summary>
    private static int? ReadStackCount(McReader r)
    {
        var count = r.VarInt();
        if (count <= 0)
            return 0;
        r.VarInt(); // item id
        var added = r.VarInt();
        var removed = r.VarInt();
        if (added > 0)
            return null;
        for (var i = 0; i < removed; i++)
            r.VarInt();
        return count;
    }

    private void SetHotbar(int slot, int? count)
    {
        if (slot is < 0 or > 8)
            return;
        lock (hotbar)
            hotbar[slot] = count ?? -1;
    }

    /// <summary>The last world packet that could not be read (the connection carries on; the world model may lag).</summary>
    public string? LastWorldError { get; private set; }

    private async Task WorldPacketAsync(int id, McReader r, CancellationToken ct)
    {
        try
        {
            await ReadWorldPacketAsync(id, r, ct).ConfigureAwait(false);
        }
        catch (Exception e) when (e is EndOfStreamException or InvalidDataException or IndexOutOfRangeException or ArgumentException)
        {
            LastWorldError = $"packet 0x{id:X2}: {e.Message}";
            if (Environment.GetEnvironmentVariable("AIJADE_MC_DUMP") is { Length: > 0 } dump)
                await File.WriteAllBytesAsync(Path.Combine(dump, $"packet-{id:X2}.bin"), r.Payload, ct).ConfigureAwait(false);
        }
    }

    private async Task ReadWorldPacketAsync(int id, McReader r, CancellationToken ct)
    {
        switch (id)
        {
            case CChunk:
                World.LoadChunk(r);
                break;
            case CChunkBatchFinished:
                // Without this acknowledgement the server stops sending chunks after the first batches.
                await connection!.WriteAsync(SChunkBatchReceived, new McWriter().Float(20f), ct).ConfigureAwait(false);
                break;
            case CForgetChunk:
                var cz = r.Int();
                World.Unload(r.Int(), cz);
                break;
            case CBlockUpdate:
                World.SetBlock(BlockPos.Unpack(r.Long()), r.VarInt());
                break;
            case CSectionBlocksUpdate:
                World.UpdateSection(r);
                break;
            case CBlockChangedAck:
                break;
            case CContainerSetContent:
                TrackContent(Fork(r));
                if (r.VarInt() != 0)
                    break; // only the player's own inventory (window 0) matters here
                r.VarInt(); // state id
                var slots = r.VarInt();
                for (var i = 0; i < slots; i++)
                {
                    var count = ReadStackCount(r);
                    SetHotbar(i - 36, count); // window slots 36–44 are the hotbar
                    if (count is null)
                    {
                        for (var k = Math.Max(i + 1, 36); k <= 44; k++)
                            SetHotbar(k - 36, null);
                        break;
                    }
                }
                break;
            case CContainerSetSlot:
                TrackSetSlot(Fork(r));
                var window = r.VarInt();
                r.VarInt(); // state id
                var at = r.Short();
                if (window == 0 && at is >= 36 and <= 44)
                    SetHotbar(at - 36, ReadStackCount(r));
                break;
            case CSetPlayerInventory:
                var inventorySlot = r.VarInt(); // inventory index: 0–8 are the hotbar
                var fork = Fork(r);
                SetHotbar(inventorySlot, ReadStackCount(r));
                // inventory index → window-0 slot: hotbar 0–8 is 36–44, the main inventory 9–35 keeps its number
                if (inventorySlot is >= 0 and <= 35)
                    TrackSlot(0, inventorySlot < 9 ? inventorySlot + 36 : inventorySlot, ReadStack(fork));
                break;
            case CRecipeBookAdd:
                ReadRecipeBookAdd(r);
                break;
            case CRecipeBookRemove:
                ReadRecipeBookRemove(r);
                break;
            case COpenScreen:
                ReadOpenScreen(r);
                break;
            case CSetHeldSlot:
                selected = r.VarInt();
                break;
            case CAddEntity:
                var eid = r.VarInt();
                var uuid = r.Uuid();
                var type = r.VarInt();
                World.AddEntity(new McEntity(eid, uuid, type, r.Double(), r.Double(), r.Double()));
                break;
            case CMoveEntityPos or CMoveEntityPosRot:
                // 26.3: entity id, then (step count << 1 | on ground); no steps = one delta, else per step a tick count and a
                // delta. Every delta is relative to the same base (the last known position), so the last one is the end.
                var mover = r.VarInt();
                var steps = r.VarInt() >>> 1;
                double mx = 0, my = 0, mz = 0;
                for (var i = 0; i < Math.Max(1, steps); i++)
                {
                    if (steps > 0)
                        r.VarInt(); // ticks of this step
                    (mx, my, mz) = (r.Short() / 4096.0, r.Short() / 4096.0, r.Short() / 4096.0);
                }
                World.MoveEntity(mover, mx, my, mz);
                break;
            case CEntityPositionSync:
                // 26.3: entity id, a position path (0 = one position, 1 = steps of position + ticks; the last is where it is).
                var synced = r.VarInt();
                if (r.VarInt() == 0)
                {
                    World.PlaceEntity(synced, r.Double(), r.Double(), r.Double());
                }
                else
                {
                    var count = r.VarInt();
                    double sx = 0, sy = 0, sz = 0;
                    for (var i = 0; i < count; i++)
                    {
                        (sx, sy, sz) = (r.Double(), r.Double(), r.Double());
                        r.VarInt();
                    }
                    if (count > 0)
                        World.PlaceEntity(synced, sx, sy, sz);
                }
                break;
            case CTeleportEntity:
                World.PlaceEntity(r.VarInt(), r.Double(), r.Double(), r.Double());
                break;
            case CRemoveEntities:
                var n = r.VarInt();
                for (var i = 0; i < n; i++)
                    World.RemoveEntity(r.VarInt());
                break;
            default:
                break;
        }
    }

    /// <summary>The block the client stands in (feet).</summary>
    public BlockPos Feet
    {
        get
        {
            lock (motion)
                return BlockPos.Of(x, y + 0.01, z);
        }
    }

    /// <summary>
    /// A movement packet closes its client tick: since 26.x the server disconnects a client that reports a position twice
    /// in one tick, and only "client tick end" starts the next.
    /// </summary>
    private async Task SendMovementAsync(int packet, McWriter body, CancellationToken ct)
    {
        await connection!.WriteAsync(packet, body, ct).ConfigureAwait(false);
        await connection.WriteAsync(SClientTickEnd, new McWriter(), ct).ConfigureAwait(false);
    }

    private Task SendPositionAsync(double px, double py, double pz, bool onGround, CancellationToken ct) =>
        SendMovementAsync(SMovePlayerPos, new McWriter().Double(px).Double(py).Double(pz).Byte((byte)(onGround ? 1 : 0)), ct);

    /// <summary>Turn to look at a point (yaw/pitch as the game measures them) and tell the server.</summary>
    public async Task LookAtAsync(double tx, double ty, double tz, CancellationToken ct)
    {
        double px, py, pz;
        float nyaw, npitch;
        lock (motion)
        {
            double dx = tx - x, dy = ty - (y + 1.62), dz = tz - z;
            nyaw = (float)(-Math.Atan2(dx, dz) * 180 / Math.PI);
            npitch = (float)(-Math.Atan2(dy, Math.Sqrt((dx * dx) + (dz * dz))) * 180 / Math.PI);
            (yaw, pitch) = (nyaw, npitch);
            (px, py, pz) = (x, y, z);
        }
        await SendMovementAsync(SMovePlayerPosRot, new McWriter().Double(px).Double(py).Double(pz).Float(nyaw).Float(npitch).Byte(1), ct).ConfigureAwait(false);
        await Task.Delay(50, ct).ConfigureAwait(false); // one tick per movement report
    }

    /// <summary>
    /// Walk a path of standing positions, one tick at a time. Steps up are taken as a short hop (straight up, then across),
    /// drops as a fall after leaving the edge; in water and on ladders or vines the client swims or climbs instead, more slowly. Stops early when cancelled or when the server teleports the client (for
    /// example after a movement it rejected), returning false.
    /// </summary>
    public async Task<bool> WalkAsync(IReadOnlyList<BlockPos> path, CancellationToken ct)
    {
        lock (motion)
            teleported = false;
        foreach (var target in path)
        {
            double tx = target.X + 0.5, ty = target.Y, tz = target.Z + 0.5;
            double cy;
            lock (motion)
                cy = y;
            // swimming or climbing: no hops or falls, slower moves (vanilla climbs about 0.12 blocks and swims about 0.1 per tick);
            // up is taken in the current column before moving across, down only once above the target (the column left may be solid)
            var slow = World.IsSwimOrClimb(target) || World.IsSwimOrClimb(Feet);
            if (slow && ty > cy + 0.01)
            {
                var vy = cy;
                while (ty - vy > 0.001)
                {
                    vy = Math.Min(ty, vy + 0.12);
                    if (!await TickToAsync(null, vy, null, false, ct).ConfigureAwait(false))
                        return false;
                }
                cy = vy;
            }
            else if (!slow && ty > cy + 0.01)
            {
                // hop: rise in place first (the block above is free; the path finder checked the head room)
                foreach (var rise in new[] { 0.42, 0.75, 1.0 })
                {
                    if (!await TickToAsync(null, cy + Math.Min(rise, ty - cy), null, false, ct).ConfigureAwait(false))
                        return false;
                }
            }
            while (true)
            {
                double dx, dz;
                lock (motion)
                {
                    dx = tx - x;
                    dz = tz - z;
                }
                var dist = Math.Sqrt((dx * dx) + (dz * dz));
                if (dist < 0.05)
                    break;
                var k = Math.Min(1, (slow ? WalkStep / 2 : WalkStep) / dist);
                double nx, nz;
                lock (motion)
                {
                    nx = x + (dx * k);
                    nz = z + (dz * k);
                }
                if (!await TickToAsync(nx, null, nz, !slow && ty >= cy - 0.01, ct).ConfigureAwait(false))
                    return false;
            }
            // sink or climb down to the target level, or fall to it
            double fy;
            lock (motion)
                fy = y;
            while (slow && fy > ty + 0.001)
            {
                fy = Math.Max(ty, fy - 0.15);
                if (!await TickToAsync(null, fy, null, false, ct).ConfigureAwait(false))
                    return false;
            }
            var fall = 0.0;
            while (fy > ty + 0.001)
            {
                fall = Math.Min(fall + 0.08, 0.6);
                fy = Math.Max(ty, fy - fall);
                if (!await TickToAsync(null, fy, null, fy <= ty + 0.001, ct).ConfigureAwait(false))
                    return false;
            }
        }
        return true;
    }

    /// <summary>One game tick of movement: update the position, send it, wait for the tick to pass.</summary>
    private async Task<bool> TickToAsync(double? nx, double? ny, double? nz, bool onGround, CancellationToken ct)
    {
        double px, py, pz;
        lock (motion)
        {
            if (teleported)
                return false;
            x = nx ?? x;
            y = ny ?? y;
            z = nz ?? z;
            (px, py, pz) = (x, y, z);
        }
        await SendPositionAsync(px, py, pz, onGround, ct).ConfigureAwait(false);
        await Task.Delay(50, ct).ConfigureAwait(false);
        return true;
    }

    /// <summary>Find a path to within <paramref name="near"/> blocks of a position and walk it.</summary>
    public async Task<bool> GoToAsync(BlockPos goal, double near, CancellationToken ct)
    {
        for (var attempt = 0; attempt < 3; attempt++)
        {
            var start = Feet;
            if (Math.Sqrt(Math.Pow(start.X - goal.X, 2) + Math.Pow(start.Z - goal.Z, 2)) <= Math.Max(near, 0.5) && Math.Abs(start.Y - goal.Y) <= 2)
                return true;
            var path = World.FindPath(start, goal, near);
            if (path is null)
                return false;
            if (await WalkAsync(path, ct).ConfigureAwait(false))
                return true;
            await Task.Delay(200, ct).ConfigureAwait(false); // the server moved us back: re-plan from where we are
        }
        return false;
    }

    /// <summary>The face of <paramref name="block"/> that points towards the eyes (0 down, 1 up, 2 north, 3 south, 4 west, 5 east).</summary>
    private int FaceTowardsEyes(BlockPos block)
    {
        double ex, ey, ez;
        lock (motion)
            (ex, ey, ez) = (x, y + 1.62, z);
        double dx = ex - (block.X + 0.5), dy = ey - (block.Y + 0.5), dz = ez - (block.Z + 0.5);
        var ax = Math.Abs(dx);
        var ay = Math.Abs(dy);
        var az = Math.Abs(dz);
        return ay >= ax && ay >= az ? (dy > 0 ? 1 : 0) : ax >= az ? (dx > 0 ? 5 : 4) : (dz > 0 ? 3 : 2);
    }

    private double EyeDistance(BlockPos block)
    {
        lock (motion)
            return Math.Sqrt(Math.Pow(x - (block.X + 0.5), 2) + Math.Pow(y + 1.62 - (block.Y + 0.5), 2) + Math.Pow(z - (block.Z + 0.5), 2));
    }

    private async Task<bool> WaitForBlockAsync(BlockPos p, Func<int, bool> condition, TimeSpan timeout, CancellationToken ct)
    {
        var done = new TaskCompletionSource(TaskCreationOptions.RunContinuationsAsynchronously);
        void OnChange(BlockPos at, int id)
        {
            if (at == p && condition(id))
                done.TrySetResult();
        }
        World.BlockChanged += OnChange;
        try
        {
            if (condition(World.BlockAt(p)))
                return true;
            var finished = await Task.WhenAny(done.Task, Task.Delay(timeout, ct)).ConfigureAwait(false);
            return finished == done.Task;
        }
        finally
        {
            World.BlockChanged -= OnChange;
        }
    }

    /// <summary>
    /// Dig a block within reach as a survival player does: start digging, then report it finished; the server refuses a
    /// finish that comes too early for the block and tool, so the finish is repeated with growing waits until the block
    /// update shows air (or ten seconds pass).
    /// </summary>
    public async Task<bool> DigAsync(BlockPos block, CancellationToken ct)
    {
        if (McWorld.IsAir(World.BlockAt(block)))
            return true;
        if (EyeDistance(block) > Reach)
            throw new InvalidOperationException($"{block} is out of reach");
        await LookAtAsync(block.X + 0.5, block.Y + 0.5, block.Z + 0.5, ct).ConfigureAwait(false);
        var face = FaceTowardsEyes(block);
        await connection!.WriteAsync(SPlayerAction, new McWriter().VarInt(StartDigging).Long(block.Packed).Byte((byte)face).VarInt(Interlocked.Increment(ref sequence)), ct).ConfigureAwait(false);
        var wait = TimeSpan.FromMilliseconds(250);
        var deadline = DateTimeOffset.UtcNow + TimeSpan.FromSeconds(10);
        while (DateTimeOffset.UtcNow < deadline)
        {
            if (await WaitForBlockAsync(block, McWorld.IsAir, wait, ct).ConfigureAwait(false))
                return true; // creative mode, or an instantly broken block
            await connection.WriteAsync(SPlayerAction, new McWriter().VarInt(FinishDigging).Long(block.Packed).Byte((byte)face).VarInt(Interlocked.Increment(ref sequence)), ct).ConfigureAwait(false);
            if (await WaitForBlockAsync(block, McWorld.IsAir, TimeSpan.FromMilliseconds(400), ct).ConfigureAwait(false))
                return true;
            // too early: start again and wait longer before the next finish
            await connection.WriteAsync(SPlayerAction, new McWriter().VarInt(StartDigging).Long(block.Packed).Byte((byte)face).VarInt(Interlocked.Increment(ref sequence)), ct).ConfigureAwait(false);
            wait *= 1.6;
        }
        await connection.WriteAsync(SPlayerAction, new McWriter().VarInt(AbortDigging).Long(block.Packed).Byte((byte)face).VarInt(Interlocked.Increment(ref sequence)), ct).ConfigureAwait(false);
        return false;
    }

    /// <summary>
    /// Place the held block at <paramref name="target"/> (which must be air) against a solid neighbour, as a click on that
    /// neighbour's face. True when the server's block update shows a block there.
    /// </summary>
    public async Task<bool> PlaceAsync(BlockPos target, CancellationToken ct)
    {
        if (!McWorld.IsAir(World.BlockAt(target)))
            throw new InvalidOperationException($"{target} is not empty");
        var feet = Feet;
        if (target == feet || target == feet.Up())
            throw new InvalidOperationException("that is where I am standing");
        // neighbour offset → the face of the neighbour that touches the target
        (int dx, int dy, int dz, int face)[] around = [(0, -1, 0, 1), (0, 1, 0, 0), (0, 0, -1, 3), (0, 0, 1, 2), (-1, 0, 0, 5), (1, 0, 0, 4)];
        foreach (var (dx, dy, dz, face) in around)
        {
            var against = target.Offset(dx, dy, dz);
            if (!McWorld.IsSolid(World.BlockAt(against)))
                continue;
            if (EyeDistance(against) > Reach + 0.5)
                throw new InvalidOperationException($"{target} is out of reach");
            await LookAtAsync(target.X + 0.5, target.Y + 0.5, target.Z + 0.5, ct).ConfigureAwait(false);
            // cursor: the middle of the clicked face, in the clicked block's coordinates
            var (cx, cy, cz) = face switch { 0 => (0.5f, 0f, 0.5f), 1 => (0.5f, 1f, 0.5f), 2 => (0.5f, 0.5f, 0f), 3 => (0.5f, 0.5f, 1f), 4 => (0f, 0.5f, 0.5f), _ => (1f, 0.5f, 0.5f) };
            // The held item first; then the other hotbar slots that hold something (all of them when the hotbar is unknown).
            // Without an item table the client cannot tell a block from a tool, so it tries until a block appears.
            var counts = Hotbar;
            var order = new[] { selected }.Concat(Enumerable.Range(0, 9).Where(i => i != selected))
                .Where(i => counts[i] != 0).ToList();
            foreach (var slot in order)
            {
                if (slot != selected)
                    await SelectSlotAsync(slot, ct).ConfigureAwait(false);
                await connection!.WriteAsync(SUseItemOn, new McWriter().VarInt(0).Long(against.Packed).VarInt(face).Float(cx).Float(cy).Float(cz).Bool(false).Bool(false)
                    .VarInt(Interlocked.Increment(ref sequence)), ct).ConfigureAwait(false);
                if (await WaitForBlockAsync(target, id => !McWorld.IsAir(id), TimeSpan.FromSeconds(1.5), ct).ConfigureAwait(false))
                    return true;
            }
            return false;
        }
        throw new InvalidOperationException($"there is nothing to place a block against at {target}");
    }

    /// <summary>Hold the item in hotbar slot 0–8.</summary>
    public async Task SelectSlotAsync(int slot, CancellationToken ct)
    {
        if (slot is < 0 or > 8)
            throw new ArgumentOutOfRangeException(nameof(slot));
        await connection!.WriteAsync(SSetCarriedItem, new McWriter().Short((short)slot), ct).ConfigureAwait(false);
        selected = slot;
    }

    private static double Distance(McEntity e, double px, double py, double pz) =>
        Math.Sqrt(Math.Pow(e.X - px, 2) + Math.Pow(e.Y - py, 2) + Math.Pow(e.Z - pz, 2));

    /// <summary>
    /// Pick up dropped items within <paramref name="radius"/> blocks of the client (of <paramref name="around"/> when given):
    /// walk onto each one; the server hands it over when the player is close. Returns how many were picked up.
    /// </summary>
    public async Task<int> CollectAsync(double radius, CancellationToken ct, BlockPos? around = null)
    {
        var picked = 0;
        for (var attempt = 0; attempt < 16; attempt++)
        {
            double px, py, pz;
            lock (motion)
                (px, py, pz) = around is { } a ? (a.X + 0.5, a.Y, a.Z + 0.5) : (x, y, z);
            var item = World.Entities(McWorld.ItemType).Where(e => Distance(e, px, py, pz) <= radius)
                .OrderBy(e => Distance(e, x, y, z)).FirstOrDefault();
            if (item is null)
                break;
            await GoToAsync(BlockPos.Of(item.X, item.Y + 0.1, item.Z), 0, ct).ConfigureAwait(false);
            // the server picks the item up within a tick or two of the player standing on it
            for (var i = 0; i < 20 && World.Entity(item.Id) is not null; i++)
                await Task.Delay(50, ct).ConfigureAwait(false);
            if (World.Entity(item.Id) is null)
                picked++;
            else
                World.RemoveEntity(item.Id); // unreachable or not ours to take: forget it rather than loop
        }
        return picked;
    }

    /// <summary>
    /// Attack an entity until it is gone (killed or out of sight) or <paramref name="timeout"/> passes: keep within reach,
    /// face it, and strike once per attack cooldown. Returns true when the entity disappeared.
    /// </summary>
    public async Task<bool> AttackAsync(int entityId, TimeSpan timeout, CancellationToken ct)
    {
        var until = DateTimeOffset.UtcNow + timeout;
        while (DateTimeOffset.UtcNow < until)
        {
            if (World.Entity(entityId) is not { } e)
                return true;
            double px, py, pz;
            lock (motion)
                (px, py, pz) = (x, y, z);
            if (Distance(e, px, py, pz) > 3)
            {
                var path = World.FindPath(Feet, BlockPos.Of(e.X, e.Y, e.Z), 2);
                if (path is null)
                    return false;
                await WalkAsync(path.Take(6).ToList(), ct).ConfigureAwait(false);
                continue;
            }
            await LookAtAsync(e.X, e.Y + 0.5, e.Z, ct).ConfigureAwait(false);
            await connection!.WriteAsync(SAttack, new McWriter().VarInt(entityId), ct).ConfigureAwait(false);
            await Task.Delay(650, ct).ConfigureAwait(false); // a bare hand's attack cooldown is 0.625 s
        }
        return World.Entity(entityId) is null;
    }
}
