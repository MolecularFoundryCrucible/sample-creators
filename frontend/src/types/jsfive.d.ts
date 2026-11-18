declare module "jsfive" {
  export class Dataset {
    readonly name: string
    readonly file: File
    readonly parent: Group
    readonly shape: number[]
    readonly dtype: string
    readonly fillvalue: unknown
    readonly attrs: Record<string, unknown>
    readonly value: unknown
    constructor(name: string, dataobjects: unknown, parent: Group)
  }

  export class Group {
    readonly name: string
    readonly file: File
    readonly parent: Group
    readonly attrs: Record<string, unknown>
    readonly keys: string[]
    readonly values: Array<Group | Dataset | null>
    constructor(name: string, dataobjects: unknown, parent?: Group | null, getterProxy?: boolean)
    get(path: string | number): Group | Dataset | null | undefined
    visit(func: (name: string) => unknown): unknown
    visititems(func: (name: string, obj: Group | Dataset) => unknown): unknown
    length(): number
  }

  export class File extends Group {
    readonly filename: string
    readonly mode: string
    readonly userblock_size: number
    constructor(fh: ArrayBuffer, filename?: string)
  }

  export class Filters {}
}
