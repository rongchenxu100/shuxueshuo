import { ReviewList } from "./review-ui";
import { ProductList } from "./product-ui";
export default function Page() { return process.env.REVIEW_BACKEND === 'legacy' ? <ReviewList /> : <ProductList />; }
