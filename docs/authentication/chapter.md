# Chapter

Requesting Trade data through chapter auth grant

## Approaches

### Eager
load all data when
the chapter is being requested

#### Pros
- Potentially faster (no waterfall on client)

#### Cons
- Somewhat complex to implement, because every Node needs different data


### Lazy
Request additional data on client

#### Pros
- more flexible as there is no need to eagerly load all data

#### Cons
- (Waterfalls)
- How to exactly authenticate on the endpoint?
  - Querying the chapter and searching for the data
  - Indexing the chapter and then checking
