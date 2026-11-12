// Stand-in for crucible-hub's result/errors modules, so uploads.ts can be copied unchanged.

export type ApiErrorDetails = {
  message: string
  retryable: boolean
  retryAfterSeconds?: number
  status?: number
  code?: string
  kind?: string
  correlationId?: string
}

export class HubApiClientError extends Error {
  readonly details: ApiErrorDetails

  constructor(details: ApiErrorDetails) {
    super(details.message)
    this.name = "HubApiClientError"
    this.details = details
  }
}
