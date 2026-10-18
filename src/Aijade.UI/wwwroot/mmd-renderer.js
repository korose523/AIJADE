// MMD renderer adapter. It needs the MMD backend (Babylon.js + babylon-mmd, both MIT) installed under
// _content/Aijade.UI/lib/; until then create() fails and the stage falls back to the built-in avatar, reporting why.
export class MmdRenderer {
  static async create(canvas, options) {
    let backend;
    try {
      backend = await import('./lib/mmd-backend.js');
    } catch {
      throw new Error('the MMD backend (babylon.js + babylon-mmd) is not installed');
    }
    return backend.createMmdStage(canvas, options);
  }
}
