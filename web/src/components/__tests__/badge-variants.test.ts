import { describe, expect, it } from 'vitest'
import { badgeVariants } from '~/components/ui/badge'
describe('badge cva variants', => {
 it('should include emerald classes for success variant', => {
 const result = badgeVariants({ variant: 'success' })
 expect(result).toContain('emerald')
 })
 it('should include amber classes for warning variant', => {
 const result = badgeVariants({ variant: 'warning' })
 expect(result).toContain('amber')
 })
 it('should include teal classes for info variant', => {
 const result = badgeVariants({ variant: 'info' })
 expect(result).toContain('teal')
 })
 it('should include gray classes for muted variant', => {
 const result = badgeVariants({ variant: 'muted' })
 expect(result).toContain('gray')
 })
 it('should still support existing variants', => {
 expect(badgeVariants({ variant: 'default' })).toContain('bg-primary')
 expect(badgeVariants({ variant: 'secondary' })).toContain('bg-secondary')
 expect(badgeVariants({ variant: 'destructive' })).toContain('bg-destructive')
 expect(badgeVariants({ variant: 'outline' })).toContain('text-foreground')
 })
})
