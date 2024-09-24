import {forwardRef} from 'react';

import type {SVGIconProps} from './svgIcon';
import {SvgIcon} from './svgIcon';

const IconDiscord = forwardRef<SVGSVGElement, SVGIconProps>((props, ref) => {
  return (
    <SvgIcon {...props} ref={ref}>
      <path d="M13.553 3.042A12.986 12.986 0 0 0 10.253 2c-.156.286-.298.58-.423.882a11.982 11.982 0 0 0-3.664 0A9.454 9.454 0 0 0 5.744 2c-1.141.2-2.252.55-3.304 1.045C.351 6.217-.215 9.31.068 12.359a13.176 13.176 0 0 0 4.048 2.085c.328-.452.618-.932.867-1.434a8.518 8.518 0 0 1-1.365-.67c.115-.085.227-.172.335-.258A9.308 9.308 0 0 0 8 13.01c1.4 0 2.781-.317 4.047-.928.11.092.222.18.335.259a8.543 8.543 0 0 1-1.368.67c.249.502.539.982.867 1.433a13.115 13.115 0 0 0 4.051-2.084c.332-3.536-.568-6.6-2.379-9.318Zm-8.21 7.442c-.79 0-1.442-.735-1.442-1.64 0-.903.63-1.645 1.439-1.645s1.456.742 1.442 1.646c-.014.904-.636 1.639-1.44 1.639Zm5.315 0c-.79 0-1.44-.735-1.44-1.64 0-.903.63-1.645 1.44-1.645.81 0 1.452.742 1.438 1.646-.014.904-.634 1.639-1.438 1.639Z" />
    </SvgIcon>
  );
});

IconDiscord.displayName = 'IconDiscord';

export {IconDiscord};